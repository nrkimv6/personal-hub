from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.popup_url_monitor import PopupUrlMonitor
from app.models.popup_url_monitor_run import PopupUrlMonitorRun
from app.modules.naver_popup_monitor.services.diff_service import calculate_popup_diff
from app.modules.naver_popup_monitor.services.fetcher import PopupFetcher
from app.modules.naver_popup_monitor.services.place_reservation_monitor import (
    collect_place_reservation_sample,
)
from app.modules.naver_popup_monitor.services.popup_parser import parse_popup_items_from_html
from app.shared.notification import NotificationService

logger = logging.getLogger(__name__)


@dataclass
class PopupMonitorRunOutcome:
    monitor_id: int
    run_id: int
    status: str
    new_count: int
    has_new: bool
    request_profile: str | None
    proxy_url: str | None
    fallback_applied: bool
    error_message: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitor_id": self.monitor_id,
            "run_id": self.run_id,
            "status": self.status,
            "new_count": self.new_count,
            "has_new": self.has_new,
            "request_profile": self.request_profile,
            "proxy_url": self.proxy_url,
            "fallback_applied": self.fallback_applied,
            "error_message": self.error_message,
        }


def _load_snapshot_items(snapshot_json: str | None) -> list[dict[str, Any]]:
    if not snapshot_json:
        return []
    try:
        payload = json.loads(snapshot_json)
    except Exception:
        return []
    if isinstance(payload, dict):
        items = payload.get("items", [])
        return items if isinstance(items, list) else []
    if isinstance(payload, list):
        return payload
    return []


def _load_snapshot_available(snapshot_json: str | None) -> bool:
    if not snapshot_json:
        return False
    try:
        payload = json.loads(snapshot_json)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    reservation_state = payload.get("reservation_state")
    if not isinstance(reservation_state, dict):
        return False
    return bool(reservation_state.get("available"))


def _build_notification_message(
    monitor: PopupUrlMonitor,
    outcome: PopupMonitorRunOutcome,
) -> str:
    if getattr(monitor, "monitor_kind", "popup_list") == "place_reservation":
        snapshot = None
        if monitor.latest_snapshot_json:
            try:
                snapshot = json.loads(monitor.latest_snapshot_json)
            except Exception:
                snapshot = None
        reservation_state = snapshot.get("reservation_state", {}) if isinstance(snapshot, dict) else {}
        signals = snapshot.get("signals", []) if isinstance(snapshot, dict) else []
        signal_lines = []
        for signal in signals:
            if not isinstance(signal, dict):
                continue
            detail = signal.get("url") or signal.get("value") or "-"
            signal_lines.append(f"- {signal.get('kind') or 'signal'}: {detail}")
        signal_text = "\n".join(signal_lines) if signal_lines else "- signal: available"
        return (
            "[네이버 Place 예약 신호 감지]\n"
            f"- monitor_id: {monitor.id}\n"
            f"- name: {monitor.name or '(unnamed)'}\n"
            f"- url: {monitor.url}\n"
            f"- bookingBusinessId: {reservation_state.get('booking_business_id') or '-'}\n"
            f"- bookingUrl: {reservation_state.get('booking_url') or '-'}\n"
            f"- ticket_count: {reservation_state.get('ticket_count') or 0}\n"
            f"{signal_text}"
        )

    return (
        "[네이버 팝업 URL 모니터] 신규 항목 감지\n"
        f"- monitor_id: {monitor.id}\n"
        f"- name: {monitor.name or '(unnamed)'}\n"
        f"- new_count: {outcome.new_count}\n"
        f"- profile: {outcome.request_profile or '-'}\n"
        f"- proxy: {outcome.proxy_url or 'direct'}"
    )


class PopupMonitorService:
    def __init__(
        self,
        fetcher: PopupFetcher | None = None,
        notification_service: Any | None = None,
    ):
        self._fetcher = fetcher or PopupFetcher()
        self._notification_service = notification_service or NotificationService()

    async def close(self) -> None:
        await self._fetcher.close()

    async def run_monitor_once(
        self,
        db: Session,
        monitor: PopupUrlMonitor,
        *,
        trigger: str = "manual",
    ) -> PopupMonitorRunOutcome:
        if getattr(monitor, "monitor_kind", "popup_list") == "place_reservation":
            return await self._run_place_reservation_once(db, monitor, trigger=trigger)
        return await self._run_popup_list_once(db, monitor, trigger=trigger)

    async def _run_popup_list_once(
        self,
        db: Session,
        monitor: PopupUrlMonitor,
        *,
        trigger: str,
    ) -> PopupMonitorRunOutcome:
        started_at = datetime.now()
        fetch_result = await self._fetcher.fetch_popup_html(
            url=monitor.url,
            request_profile=monitor.request_profile,
            fallback_strategy=monitor.fallback_strategy,
            monitor_proxy_enabled=bool(monitor.proxy_enabled),
        )
        finished_at = datetime.now()

        if not fetch_result.success:
            db.refresh(monitor)
            run = PopupUrlMonitorRun(
                monitor_id=monitor.id,
                status="error",
                new_count=0,
                has_new=False,
                proxy_url=fetch_result.proxy_url,
                request_profile=fetch_result.request_profile or monitor.request_profile,
                fallback_applied=fetch_result.fallback_applied,
                snapshot_json=None,
                error_message=fetch_result.error or "fetch_failed",
                started_at=started_at,
                finished_at=finished_at,
            )
            db.add(run)
            if self._should_update_latest(monitor, started_at):
                monitor.latest_checked_at = finished_at
                monitor.updated_at = finished_at
            db.commit()
            db.refresh(run)
            db.refresh(monitor)
            return PopupMonitorRunOutcome(
                monitor_id=monitor.id,
                run_id=run.id,
                status=run.status,
                new_count=0,
                has_new=False,
                request_profile=run.request_profile,
                proxy_url=run.proxy_url,
                fallback_applied=bool(run.fallback_applied),
                error_message=run.error_message,
            )

        db.refresh(monitor)
        parse_result = parse_popup_items_from_html(fetch_result.html)
        current_items = [item.to_dict() for item in parse_result.items]
        previous_items = _load_snapshot_items(monitor.latest_snapshot_json)
        diff_summary = calculate_popup_diff(previous_items, current_items)

        snapshot_payload = {
            "items": current_items,
            "meta": {
                "trigger": trigger,
                "checked_at": finished_at.isoformat(),
                "request_profile": fetch_result.request_profile,
                "proxy_url": fetch_result.proxy_url,
                "fallback_applied": fetch_result.fallback_applied,
                "fetch_status": fetch_result.status,
                "fetch_final_url": fetch_result.final_url,
                "apollo_found": parse_result.has_apollo_state,
                "apollo_parse_error": parse_result.parse_error,
                "root_query_key_count": parse_result.root_query_key_count,
                "root_query_popup_keys": parse_result.root_query_popup_keys,
            },
            "diff": diff_summary.to_dict(),
        }
        snapshot_json = json.dumps(snapshot_payload, ensure_ascii=False)
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()

        run_status = "success" if parse_result.parse_error is None else "partial"
        run = PopupUrlMonitorRun(
            monitor_id=monitor.id,
            status=run_status,
            new_count=diff_summary.new_count,
            has_new=diff_summary.has_new,
            proxy_url=fetch_result.proxy_url,
            request_profile=fetch_result.request_profile or monitor.request_profile,
            fallback_applied=fetch_result.fallback_applied,
            snapshot_json=snapshot_json,
            error_message=parse_result.parse_error,
            started_at=started_at,
            finished_at=finished_at,
        )
        db.add(run)

        if self._should_update_latest(monitor, started_at):
            monitor.latest_snapshot_json = snapshot_json
            monitor.latest_snapshot_hash = snapshot_hash
            monitor.latest_checked_at = finished_at
            monitor.updated_at = finished_at

        db.commit()
        db.refresh(run)
        db.refresh(monitor)

        outcome = PopupMonitorRunOutcome(
            monitor_id=monitor.id,
            run_id=run.id,
            status=run.status,
            new_count=run.new_count,
            has_new=bool(run.has_new),
            request_profile=run.request_profile,
            proxy_url=run.proxy_url,
            fallback_applied=bool(run.fallback_applied),
            error_message=run.error_message,
        )
        await self._notify_if_needed(monitor, outcome)
        return outcome

    async def _run_place_reservation_once(
        self,
        db: Session,
        monitor: PopupUrlMonitor,
        *,
        trigger: str,
    ) -> PopupMonitorRunOutcome:
        started_at = datetime.now()
        sample = await collect_place_reservation_sample(
            self._fetcher,
            monitor.url,
            browser_fallback_enabled=bool(monitor.browser_fallback_enabled),
            request_profile=monitor.request_profile,
            fallback_strategy=monitor.fallback_strategy,
            monitor_proxy_enabled=bool(monitor.proxy_enabled),
        )
        finished_at = datetime.now()
        fetch_result = sample.get("http_result")

        if not sample.get("ok"):
            db.refresh(monitor)
            error_message = "; ".join(sample.get("errors") or []) or "place_reservation_fetch_failed"
            run = PopupUrlMonitorRun(
                monitor_id=monitor.id,
                status="error",
                new_count=0,
                has_new=False,
                proxy_url=getattr(fetch_result, "proxy_url", None),
                request_profile=getattr(fetch_result, "request_profile", None) or monitor.request_profile,
                fallback_applied=bool(getattr(fetch_result, "fallback_applied", False)),
                snapshot_json=None,
                error_message=error_message,
                started_at=started_at,
                finished_at=finished_at,
            )
            db.add(run)
            if self._should_update_latest(monitor, started_at):
                monitor.latest_checked_at = finished_at
                monitor.updated_at = finished_at
            db.commit()
            db.refresh(run)
            db.refresh(monitor)
            return PopupMonitorRunOutcome(
                monitor_id=monitor.id,
                run_id=run.id,
                status=run.status,
                new_count=0,
                has_new=False,
                request_profile=run.request_profile,
                proxy_url=run.proxy_url,
                fallback_applied=bool(run.fallback_applied),
                error_message=run.error_message,
            )

        db.refresh(monitor)
        reservation_state = sample["reservation_state"]
        signals = sample.get("signals") or []
        previous_available = _load_snapshot_available(monitor.latest_snapshot_json)
        current_available = bool(reservation_state.get("available"))
        has_new = (not previous_available) and current_available
        new_count = max(1, len(signals)) if has_new else 0

        snapshot_payload = {
            "reservation_state": reservation_state,
            "signals": signals,
            "source": sample.get("source") or {},
            "meta": {
                "monitor_kind": "place_reservation",
                "trigger": trigger,
                "checked_at": finished_at.isoformat(),
                "request_profile": getattr(fetch_result, "request_profile", None) or monitor.request_profile,
                "proxy_url": getattr(fetch_result, "proxy_url", None),
                "fallback_applied": bool(getattr(fetch_result, "fallback_applied", False)),
                "fetch_status": getattr(fetch_result, "status", None),
                "fetch_final_url": getattr(fetch_result, "final_url", None),
                "errors": sample.get("errors") or [],
            },
            "diff": {
                "previous_available": previous_available,
                "available": current_available,
                "new_count": new_count,
                "has_new": has_new,
            },
        }
        snapshot_json = json.dumps(snapshot_payload, ensure_ascii=False)
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        run_status = "partial" if sample.get("errors") else "success"
        error_message = "; ".join(sample.get("errors") or []) or None

        run = PopupUrlMonitorRun(
            monitor_id=monitor.id,
            status=run_status,
            new_count=new_count,
            has_new=has_new,
            proxy_url=getattr(fetch_result, "proxy_url", None),
            request_profile=getattr(fetch_result, "request_profile", None) or monitor.request_profile,
            fallback_applied=bool(getattr(fetch_result, "fallback_applied", False)),
            snapshot_json=snapshot_json,
            error_message=error_message,
            started_at=started_at,
            finished_at=finished_at,
        )
        db.add(run)

        should_update_latest = self._should_update_latest(monitor, started_at)
        if should_update_latest:
            monitor.latest_snapshot_json = snapshot_json
            monitor.latest_snapshot_hash = snapshot_hash
            monitor.latest_checked_at = finished_at
            monitor.updated_at = finished_at

        if has_new and bool(monitor.stop_on_detected) and should_update_latest:
            monitor.is_enabled = False
            monitor.detected_at = finished_at
            monitor.updated_at = finished_at

        db.commit()
        db.refresh(run)
        db.refresh(monitor)

        outcome = PopupMonitorRunOutcome(
            monitor_id=monitor.id,
            run_id=run.id,
            status=run.status,
            new_count=run.new_count,
            has_new=bool(run.has_new),
            request_profile=run.request_profile,
            proxy_url=run.proxy_url,
            fallback_applied=bool(run.fallback_applied),
            error_message=run.error_message,
        )
        await self._notify_if_needed(monitor, outcome)
        return outcome

    async def run_monitor_by_id(
        self,
        db: Session,
        monitor_id: int,
        *,
        trigger: str = "manual",
    ) -> PopupMonitorRunOutcome:
        monitor = db.query(PopupUrlMonitor).filter(PopupUrlMonitor.id == monitor_id).first()
        if not monitor:
            raise ValueError(f"Popup monitor not found: {monitor_id}")
        return await self.run_monitor_once(db, monitor, trigger=trigger)

    async def _notify_if_needed(
        self,
        monitor: PopupUrlMonitor,
        outcome: PopupMonitorRunOutcome,
    ) -> None:
        if not outcome.has_new:
            return
        if not monitor.notify_on_new:
            return
        if outcome.new_count < int(monitor.min_new_count or 1):
            return

        should_notify = False
        if hasattr(self._notification_service, "should_notify"):
            try:
                should_notify = bool(self._notification_service.should_notify("popup_new"))
            except Exception as exc:
                logger.warning("[popup-monitor] should_notify 평가 실패: %s", exc)
        if not should_notify:
            return

        if hasattr(self._notification_service, "send_notification_message"):
            try:
                message = _build_notification_message(monitor, outcome)
                await self._notification_service.send_notification_message(
                    message,
                    send_desktop=True,
                )
            except Exception as exc:
                logger.warning("[popup-monitor] popup_new 알림 발송 실패: %s", exc)

    def get_latest_payload(self, db: Session, monitor_id: int) -> dict[str, Any]:
        monitor = db.query(PopupUrlMonitor).filter(PopupUrlMonitor.id == monitor_id).first()
        if not monitor:
            raise ValueError(f"Popup monitor not found: {monitor_id}")

        last_run = (
            db.query(PopupUrlMonitorRun)
            .filter(PopupUrlMonitorRun.monitor_id == monitor_id)
            .order_by(PopupUrlMonitorRun.started_at.desc(), PopupUrlMonitorRun.id.desc())
            .first()
        )

        snapshot_payload = None
        if monitor.latest_snapshot_json:
            try:
                snapshot_payload = json.loads(monitor.latest_snapshot_json)
            except Exception:
                snapshot_payload = None

        item_count = 0
        if isinstance(snapshot_payload, dict):
            items = snapshot_payload.get("items", [])
            if isinstance(items, list):
                item_count = len(items)

        return {
            "monitor_id": monitor.id,
            "latest_checked_at": monitor.latest_checked_at,
            "latest_snapshot_hash": monitor.latest_snapshot_hash,
            "item_count": item_count,
            "snapshot": snapshot_payload,
            "last_run": self._run_to_dict(last_run) if last_run else None,
        }

    def list_runs_payload(
        self,
        db: Session,
        monitor_id: int,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        runs = (
            db.query(PopupUrlMonitorRun)
            .filter(PopupUrlMonitorRun.monitor_id == monitor_id)
            .order_by(PopupUrlMonitorRun.id.desc())
            .limit(limit)
            .all()
        )
        return [self._run_to_dict(run) for run in runs]

    @staticmethod
    def _run_to_dict(run: PopupUrlMonitorRun) -> dict[str, Any]:
        snapshot = None
        if run.snapshot_json:
            try:
                snapshot = json.loads(run.snapshot_json)
            except Exception:
                snapshot = None
        return {
            "id": run.id,
            "monitor_id": run.monitor_id,
            "status": run.status,
            "new_count": run.new_count,
            "has_new": bool(run.has_new),
            "proxy_url": run.proxy_url,
            "request_profile": run.request_profile,
            "fallback_applied": bool(run.fallback_applied),
            "error_message": run.error_message,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "created_at": run.created_at,
            "snapshot": snapshot,
        }

    @staticmethod
    def _should_update_latest(monitor: PopupUrlMonitor, started_at: datetime) -> bool:
        if monitor.latest_checked_at is None:
            return True
        return started_at >= monitor.latest_checked_at

