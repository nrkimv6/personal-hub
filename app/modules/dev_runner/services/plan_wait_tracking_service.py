"""Automatic TrackingItem upsert for reserved/waiting plan files."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.tracking_item import TrackingItem, TrackingItemPlanLink


AUTO_WAIT_PLAN_TRACKING_MARKER = "auto_wait_plan_tracking_v1"
WAITING_PLAN_STATUS = "예약대기"
TERMINAL_PLAN_STATUSES = {"완료", "구현완료"}

_HEADER_RE = re.compile(r"^>\s*(?P<key>[^:：]+)\s*[:：]\s*(?P<value>.*)\s*$")
_ISO_DATE_RE = re.compile(
    r"(?P<value>\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}(?::\d{2})?)?)"
)
_MARKER_JSON_RE = re.compile(
    rf"{re.escape(AUTO_WAIT_PLAN_TRACKING_MARKER)}\s*(?P<json>\{{.*?\}})",
    re.DOTALL,
)


@dataclass(frozen=True)
class WaitingPlanSignal:
    path: str
    title: str
    status: str | None
    wait_until: datetime | None
    reason: str | None = None
    progress: str | None = None
    skip_reason: str | None = None

    @property
    def eligible(self) -> bool:
        return self.status == WAITING_PLAN_STATUS and self.wait_until is not None and self.skip_reason is None


@dataclass(frozen=True)
class WaitTrackingUpsertResult:
    action: str
    reason: str | None = None
    tracking_item_id: int | None = None
    plan_record_id: int | None = None
    title: str | None = None
    wait_until: datetime | None = None

    @property
    def created(self) -> bool:
        return self.action == "created"

    @property
    def updated(self) -> bool:
        return self.action == "updated"

    @property
    def skipped(self) -> bool:
        return self.action == "skipped"

    def to_summary(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "tracking_item_id": self.tracking_item_id,
            "plan_record_id": self.plan_record_id,
            "title": self.title,
            "wait_until": self.wait_until.isoformat() if self.wait_until else None,
        }


def _canonical_plan_path(plan_path: str | Path) -> str:
    return str(Path(plan_path).resolve())


def _compute_filename_hash(file_path: str | Path) -> str:
    filename = Path(file_path).name
    return hashlib.sha256(filename.encode("utf-8")).hexdigest()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    match = _ISO_DATE_RE.search(value.strip().strip("`"))
    if not match:
        return None
    raw = match.group("value").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if fmt == "%Y-%m-%d":
                return datetime.combine(parsed.date(), time.min)
            return parsed
        except ValueError:
            continue
    return None


def _extract_review_due_from_body(content: str) -> datetime | None:
    for line in content.splitlines():
        if "review_due_at" not in line:
            continue
        parsed = _parse_datetime(line)
        if parsed is not None:
            return parsed
    return None


def _extract_title(content: str, plan_path: str | Path) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or Path(plan_path).stem
    return Path(plan_path).stem


def parse_waiting_plan_signal(plan_path: str | Path) -> WaitingPlanSignal:
    canonical_path = _canonical_plan_path(plan_path)
    path = Path(canonical_path)
    if not path.exists():
        return WaitingPlanSignal(
            path=canonical_path,
            title=path.stem,
            status=None,
            wait_until=None,
            skip_reason="file_missing",
        )
    if any(part.lower() == "archive" for part in path.parts):
        return WaitingPlanSignal(
            path=canonical_path,
            title=path.stem,
            status=None,
            wait_until=None,
            skip_reason="archive_path",
        )

    content = path.read_text(encoding="utf-8", errors="replace")
    header: dict[str, str] = {}
    for line in content.splitlines()[:40]:
        match = _HEADER_RE.match(line)
        if match:
            header[match.group("key").strip()] = match.group("value").strip()

    status = header.get("상태")
    title = _extract_title(content, path)
    wait_until = _parse_datetime(header.get("검토 예정일"))
    if wait_until is None:
        wait_until = _extract_review_due_from_body(content)

    if status in TERMINAL_PLAN_STATUSES:
        skip_reason = "terminal_status"
    elif status != WAITING_PLAN_STATUS:
        skip_reason = "not_waiting_status"
    elif wait_until is None:
        skip_reason = "missing_wait_until"
    else:
        skip_reason = None

    return WaitingPlanSignal(
        path=canonical_path,
        title=title,
        status=status,
        wait_until=wait_until,
        reason=header.get("요약"),
        progress=header.get("진행률"),
        skip_reason=skip_reason,
    )


def _marker_payload(signal: WaitingPlanSignal) -> dict[str, Any]:
    return {
        "marker": AUTO_WAIT_PLAN_TRACKING_MARKER,
        "canonical_plan_path": signal.path,
        "plan_filename_hash": _compute_filename_hash(signal.path),
        "plan_status": signal.status,
        "wait_until": signal.wait_until.isoformat() if signal.wait_until else None,
    }


def _description_for_signal(signal: WaitingPlanSignal) -> str:
    payload = _marker_payload(signal)
    parts = [
        "예약대기 plan에서 자동 등록된 Tracking 항목입니다.",
        "",
        f"plan: {signal.path}",
    ]
    if signal.reason:
        parts.append(f"reason: {signal.reason}")
    if signal.progress:
        parts.append(f"progress: {signal.progress}")
    parts.extend(
        [
            "",
            AUTO_WAIT_PLAN_TRACKING_MARKER,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
    )
    return "\n".join(parts)


def _extract_marker_payload(description: str | None) -> dict[str, Any] | None:
    if not description or AUTO_WAIT_PLAN_TRACKING_MARKER not in description:
        return None
    match = _MARKER_JSON_RE.search(description)
    if not match:
        return None
    try:
        payload = json.loads(match.group("json"))
    except json.JSONDecodeError:
        return None
    if payload.get("marker") != AUTO_WAIT_PLAN_TRACKING_MARKER:
        return None
    return payload


def _find_open_tracking_item(db: Session, signal: WaitingPlanSignal) -> TrackingItem | None:
    payload = _marker_payload(signal)
    candidates = (
        db.query(TrackingItem)
        .filter(TrackingItem.completed_at.is_(None))
        .filter(TrackingItem.description.contains(AUTO_WAIT_PLAN_TRACKING_MARKER))
        .all()
    )
    filename_hash = payload["plan_filename_hash"]
    for item in candidates:
        marker = _extract_marker_payload(item.description)
        if not marker:
            continue
        if marker.get("canonical_plan_path") == signal.path:
            return item
        if marker.get("plan_filename_hash") == filename_hash:
            return item
    return None


def _ensure_plan_link(db: Session, item: TrackingItem, plan_record_id: int) -> None:
    existing = (
        db.query(TrackingItemPlanLink)
        .filter(
            TrackingItemPlanLink.tracking_item_id == item.id,
            TrackingItemPlanLink.plan_record_id == plan_record_id,
        )
        .first()
    )
    if existing is None:
        db.add(TrackingItemPlanLink(tracking_item_id=item.id, plan_record_id=plan_record_id))


def upsert_wait_tracking_for_plan(
    db: Session,
    plan_path: str | Path,
    now: datetime | None = None,
) -> WaitTrackingUpsertResult:
    """Create or update an open TrackingItem for an eligible waiting plan.

    The caller owns the transaction boundary. This function flushes so route
    handlers can return generated ids, but it does not commit.
    """
    signal = parse_waiting_plan_signal(plan_path)
    if not signal.eligible:
        return WaitTrackingUpsertResult(
            action="skipped",
            reason=signal.skip_reason,
            title=signal.title,
            wait_until=signal.wait_until,
        )

    from app.modules.dev_runner.services.plan_record_service import PlanRecordService

    item_title = f"예약대기 plan: {signal.title}"
    description = _description_for_signal(signal)
    item = _find_open_tracking_item(db, signal)
    action = "updated"
    current_time = now or datetime.now()

    if item is None:
        item = TrackingItem(
            title=item_title,
            description=description,
            start_at=signal.wait_until,
            due_at=None,
            created_at=current_time,
            updated_at=current_time,
        )
        db.add(item)
        db.flush()
        action = "created"
    else:
        item.title = item_title
        item.description = description
        item.start_at = signal.wait_until
        item.due_at = None
        item.updated_at = current_time

    record = PlanRecordService(db).get_or_create(signal.path, title=signal.title)
    _ensure_plan_link(db, item, record.id)
    db.flush()

    return WaitTrackingUpsertResult(
        action=action,
        tracking_item_id=item.id,
        plan_record_id=record.id,
        title=item.title,
        wait_until=signal.wait_until,
    )
