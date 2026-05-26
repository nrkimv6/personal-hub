"""
PlanExecutionClaim 서비스

claim lifecycle:
  queued → active → released
                 → stale (heartbeat 만료)

> 실행점유: {claim_id} 헤더 포인터와 DB row를 한 계약으로 갱신한다.
pid는 관측 필드이며 식별자 아님. 식별자는 claim_id(UUID4)와 DB row다.
"""
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Session

from app.models.plan_execution_claim import PlanExecutionClaim
from app.modules.dev_runner.schemas import PlanDetailResponse, PlanTaskExecutionClaimResponse
from app.modules.dev_runner.services.plan_item_state import (
    ACTIVE_TASK_CLAIM_STATES,
    checkbox_state,
    task_key as build_task_key,
    task_text_hash,
)
from app.modules.dev_runner.services.plan_frontmatter import (
    write_claim_id,
    clear_claim_id,
    read_claim_id,
)

logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 300  # 5분 — heartbeat 없으면 stale 후보
STALE_THRESHOLD_SECONDS = 600  # 10분 — heartbeat_at 기준 stale 판정
TASK_CLAIMS_METADATA_KEY = "task_execution_claims"


def claim_plan(
    db: Session,
    plan_path: str,
    *,
    engine: Optional[str] = None,
    session_id: Optional[str] = None,
    runner_id: Optional[str] = None,
    plan_record_id: Optional[int] = None,
    queue_after: Optional[datetime] = None,
    claim_metadata: Optional[dict] = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    write_header: bool = True,
) -> PlanExecutionClaim:
    """plan_path에 대한 queued claim을 생성하고 필요 시 헤더 포인터를 기록한다.

    중복 active/queued claim이 있으면 ClaimConflictError를 발생시킨다.
    """
    existing = get_active_claim_for_plan(db, plan_path)
    if existing:
        raise ClaimConflictError(
            f"plan already claimed: claim_id={existing.claim_id} state={existing.state}",
            existing,
        )

    claim_id = str(uuid.uuid4())
    now = datetime.now()
    metadata = dict(claim_metadata or {})
    metadata.setdefault("header_written", bool(write_header))
    claim = PlanExecutionClaim(
        claim_id=claim_id,
        plan_record_id=plan_record_id,
        plan_path=plan_path,
        state="queued",
        engine=engine,
        session_id=session_id,
        runner_id=runner_id,
        host=_hostname(),
        claimed_at=now,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
        queue_after=queue_after,
        claim_metadata=metadata,
    )
    db.add(claim)
    db.flush()

    if write_header:
        _write_header(plan_path, claim_id)
    db.commit()
    return claim


def activate_claim(
    db: Session,
    claim_id: str,
    *,
    runner_id: Optional[str] = None,
    pid: Optional[int] = None,
    branch: Optional[str] = None,
    worktree_path: Optional[str] = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> PlanExecutionClaim:
    """queued → active 전환. runner spawn 성공 시 호출한다."""
    claim = _get_claim(db, claim_id)
    now = datetime.now()
    claim.state = "active"
    if runner_id:
        claim.runner_id = runner_id
    if pid:
        claim.pid = pid
    if branch:
        claim.branch = branch
    if worktree_path:
        claim.worktree_path = worktree_path
    claim.heartbeat_at = now
    claim.lease_expires_at = now + timedelta(seconds=lease_seconds)
    db.commit()
    return claim


def heartbeat_claim(
    db: Session,
    claim_id: str,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> PlanExecutionClaim:
    """heartbeat_at과 lease_expires_at을 갱신한다."""
    claim = _get_claim(db, claim_id)
    now = datetime.now()
    claim.heartbeat_at = now
    claim.lease_expires_at = now + timedelta(seconds=lease_seconds)
    db.commit()
    return claim


def release_claim(
    db: Session,
    claim_id: str,
) -> PlanExecutionClaim:
    """active/queued → released 전환. 헤더 포인터를 빈 값으로 초기화한다."""
    claim = _get_claim(db, claim_id)
    claim.state = "released"
    claim.released_at = datetime.now()
    db.commit()

    metadata = claim.claim_metadata if isinstance(claim.claim_metadata, dict) else {}
    if metadata.get("header_written", True):
        _clear_header(claim.plan_path)
    return claim


def claim_task_execution(
    db: Session,
    plan_claim_id: str,
    *,
    task_key: Optional[str] = None,
    phase_name: Optional[str] = None,
    item_ordinal: Optional[str] = None,
    text: Optional[str] = None,
    text_hash: Optional[str] = None,
    runner_id: Optional[str] = None,
    job_id: Optional[str] = None,
    engine: Optional[str] = None,
    session_id: Optional[str] = None,
    task_claim_id: Optional[str] = None,
    state: str = "active",
) -> PlanTaskExecutionClaimResponse:
    """Append one task-level execution claim to a plan-level claim metadata list.

    The DB row remains plan-level. Task execution claims are an active read-model
    list inside ``claim_metadata`` and are targeted by their own ``task_claim_id``.
    """
    claim = _get_claim(db, plan_claim_id)
    now = datetime.now().isoformat()
    metadata = _claim_metadata_dict(claim)
    task_claim_id = task_claim_id or str(uuid.uuid4())
    resolved_text_hash = text_hash or (task_text_hash(text) if text is not None else None)
    resolved_task_key = task_key
    if resolved_task_key is None and phase_name and item_ordinal and text is not None:
        resolved_task_key = build_task_key(phase_name, str(item_ordinal), text)

    item = {
        "task_claim_id": task_claim_id,
        "state": state,
        "runner_id": runner_id,
        "job_id": job_id,
        "plan_claim_id": claim.claim_id,
        "engine": engine or claim.engine,
        "session_id": session_id or claim.session_id,
        "task_key": resolved_task_key,
        "phase_name": phase_name,
        "item_ordinal": str(item_ordinal) if item_ordinal is not None else None,
        "text_hash": resolved_text_hash,
        "started_at": now,
        "heartbeat_at": now,
        "stale": False,
    }
    metadata.setdefault(TASK_CLAIMS_METADATA_KEY, []).append(_compact_dict(item))
    claim.claim_metadata = metadata
    flag_modified(claim, "claim_metadata")
    db.commit()
    return PlanTaskExecutionClaimResponse(**_compact_dict(item))


def release_task_execution_claim(
    db: Session,
    *,
    plan_claim_id: Optional[str] = None,
    plan_path: Optional[str] = None,
    task_claim_id: Optional[str] = None,
    runner_id: Optional[str] = None,
    job_id: Optional[str] = None,
    task_key: Optional[str] = None,
) -> list[PlanTaskExecutionClaimResponse]:
    """Release matching active task claims without touching sibling claims."""
    if not any([task_claim_id, runner_id, job_id, task_key]):
        raise ValueError("task claim release requires a targeted selector")

    rows = _task_claim_rows_for_update(
        db,
        plan_claim_id=plan_claim_id,
        plan_path=plan_path,
        task_claim_id=task_claim_id,
    )
    released: list[PlanTaskExecutionClaimResponse] = []
    now = datetime.now().isoformat()

    for claim in rows:
        metadata = _claim_metadata_dict(claim)
        changed = False
        task_claims = metadata.get(TASK_CLAIMS_METADATA_KEY)
        if not isinstance(task_claims, list):
            continue
        for item in task_claims:
            if not isinstance(item, dict):
                continue
            if item.get("state") not in ACTIVE_TASK_CLAIM_STATES:
                continue
            if not _task_claim_matches(
                item,
                task_claim_id=task_claim_id,
                runner_id=runner_id,
                job_id=job_id,
                task_key=task_key,
            ):
                continue
            item["state"] = "released"
            item["released_at"] = now
            item["heartbeat_at"] = now
            item.setdefault("plan_claim_id", claim.claim_id)
            released.append(PlanTaskExecutionClaimResponse(**_compact_dict(item)))
            changed = True
        if changed:
            claim.claim_metadata = metadata
            flag_modified(claim, "claim_metadata")

    if released:
        db.commit()
    return released


def get_active_task_execution_claims_for_plan(
    db: Session,
    plan_path: str,
) -> list[PlanTaskExecutionClaimResponse]:
    """Return active task execution claims for a plan path."""
    rows = (
        db.query(PlanExecutionClaim)
        .filter(
            PlanExecutionClaim.plan_path == plan_path,
            PlanExecutionClaim.state.in_(["queued", "active"]),
        )
        .all()
    )
    result: list[PlanTaskExecutionClaimResponse] = []
    for claim in rows:
        metadata = _claim_metadata_dict(claim)
        for item in metadata.get(TASK_CLAIMS_METADATA_KEY, []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("state") not in ACTIVE_TASK_CLAIM_STATES:
                continue
            payload = dict(item)
            payload.setdefault("plan_claim_id", claim.claim_id)
            payload.setdefault("engine", claim.engine)
            payload.setdefault("session_id", claim.session_id)
            result.append(PlanTaskExecutionClaimResponse(**_compact_dict(payload)))
    return result


def attach_task_execution_claims(
    detail: PlanDetailResponse,
    claims: list[PlanTaskExecutionClaimResponse],
) -> PlanDetailResponse:
    """Attach active task claim badges to parsed plan items."""
    if not claims:
        return detail

    def _attach(item) -> None:
        matched = [claim for claim in claims if _claim_matches_item(claim, item)]
        if matched:
            item.execution_claims = matched
            if not item.checked:
                item.state = checkbox_state(item.marker, has_active_claims=True)
                if item.marker == " ":
                    item.marker = "/"
        for child in item.children:
            _attach(child)

    for phase in detail.phases:
        for item in phase.items:
            _attach(item)
    return detail


def mark_stale_claims(db: Session, threshold_seconds: int = STALE_THRESHOLD_SECONDS) -> list[PlanExecutionClaim]:
    """heartbeat_at 또는 lease_expires_at 기준으로 만료된 active/queued claim을 stale로 전환한다.

    stale claim은 자동 탈취하지 않는다. UI/API에서 명시 release/reclaim 절차를 거친다.
    """
    cutoff = datetime.now() - timedelta(seconds=threshold_seconds)
    now = datetime.now()
    candidates = (
        db.query(PlanExecutionClaim)
        .filter(
            PlanExecutionClaim.state.in_(["queued", "active"]),
            PlanExecutionClaim.lease_expires_at < now,
        )
        .all()
    )
    stale = []
    for claim in candidates:
        if claim.state == "queued" or claim.heartbeat_at is None or claim.heartbeat_at < cutoff:
            claim.state = "stale"
            stale.append(claim)
    if stale:
        db.commit()
    return stale


def get_claim_for_plan(db: Session, plan_path: str) -> Optional[PlanExecutionClaim]:
    """plan_path의 가장 최근 claim을 반환 (상태 무관)."""
    return (
        db.query(PlanExecutionClaim)
        .filter(PlanExecutionClaim.plan_path == plan_path)
        .order_by(PlanExecutionClaim.claimed_at.desc())
        .first()
    )


def get_active_claim_for_plan(db: Session, plan_path: str) -> Optional[PlanExecutionClaim]:
    """plan_path의 active 또는 queued claim을 반환."""
    return (
        db.query(PlanExecutionClaim)
        .filter(
            PlanExecutionClaim.plan_path == plan_path,
            PlanExecutionClaim.state.in_(["queued", "active"]),
        )
        .order_by(PlanExecutionClaim.claimed_at.desc())
        .first()
    )


def get_active_claim_for_runner(db: Session, runner_id: str) -> Optional[PlanExecutionClaim]:
    """runner_id의 active 또는 queued claim을 반환."""
    if not runner_id:
        return None
    return (
        db.query(PlanExecutionClaim)
        .filter(
            PlanExecutionClaim.runner_id == runner_id,
            PlanExecutionClaim.state.in_(["queued", "active"]),
        )
        .order_by(PlanExecutionClaim.claimed_at.desc())
        .first()
    )


def get_active_claims_map(db: Session, plan_paths: list[str]) -> dict[str, PlanExecutionClaim]:
    """plan_path 목록에 대한 active/queued claim을 dict{plan_path→claim}으로 반환."""
    if not plan_paths:
        return {}
    rows = (
        db.query(PlanExecutionClaim)
        .filter(
            PlanExecutionClaim.plan_path.in_(plan_paths),
            PlanExecutionClaim.state.in_(["queued", "active"]),
        )
        .all()
    )
    result: dict[str, PlanExecutionClaim] = {}
    for row in rows:
        if row.plan_path not in result or row.claimed_at > result[row.plan_path].claimed_at:
            result[row.plan_path] = row
    return result


class ClaimConflictError(Exception):
    def __init__(self, message: str, existing_claim: PlanExecutionClaim):
        super().__init__(message)
        self.existing_claim = existing_claim


# ─── internal helpers ────────────────────────────────────────────────────────


def _get_claim(db: Session, claim_id: str) -> PlanExecutionClaim:
    claim = db.query(PlanExecutionClaim).filter(PlanExecutionClaim.claim_id == claim_id).first()
    if not claim:
        raise ValueError(f"claim not found: {claim_id}")
    return claim


def _claim_metadata_dict(claim: PlanExecutionClaim) -> dict[str, Any]:
    return dict(claim.claim_metadata) if isinstance(claim.claim_metadata, dict) else {}


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _task_claim_rows_for_update(
    db: Session,
    *,
    plan_claim_id: Optional[str] = None,
    plan_path: Optional[str] = None,
    task_claim_id: Optional[str] = None,
) -> list[PlanExecutionClaim]:
    if plan_claim_id:
        return [_get_claim(db, plan_claim_id)]
    if not plan_path and not task_claim_id:
        raise ValueError("plan_claim_id or plan_path is required")
    query = db.query(PlanExecutionClaim).filter(PlanExecutionClaim.state.in_(["queued", "active"]))
    if plan_path:
        query = query.filter(PlanExecutionClaim.plan_path == plan_path)
    return query.all()


def _task_claim_matches(
    item: dict[str, Any],
    *,
    task_claim_id: Optional[str],
    runner_id: Optional[str],
    job_id: Optional[str],
    task_key: Optional[str],
) -> bool:
    if task_claim_id and item.get("task_claim_id") != task_claim_id:
        return False
    if runner_id and item.get("runner_id") != runner_id:
        return False
    if job_id and item.get("job_id") != job_id:
        return False
    if task_key and item.get("task_key") != task_key:
        return False
    return True


def _claim_matches_item(claim: PlanTaskExecutionClaimResponse, item) -> bool:
    if claim.task_key and item.task_key and claim.task_key == item.task_key:
        return True
    if claim.phase_name and item.phase_name and claim.phase_name != item.phase_name:
        return False
    if claim.item_ordinal and item.item_ordinal and claim.item_ordinal == item.item_ordinal:
        if not claim.text_hash or not item.text_hash or claim.text_hash == item.text_hash:
            return True
    if claim.text_hash and item.text_hash and claim.text_hash == item.text_hash:
        return True
    return False


def _hostname() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "unknown"


def _write_header(plan_path: str, claim_id: str) -> None:
    try:
        write_claim_id(Path(plan_path), claim_id)
    except Exception as e:
        logger.warning("claim header write failed: %s — %s", plan_path, e)


def _clear_header(plan_path: str) -> None:
    try:
        clear_claim_id(Path(plan_path))
    except Exception as e:
        logger.warning("claim header clear failed: %s — %s", plan_path, e)
