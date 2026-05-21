"""Delivery helpers for failure alert policy decisions."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Callable

from app.services.failure_alert_policy import (
    AlertDecision,
    AlertSeverity,
    FailureEvent,
    build_failure_alert_message,
    classify_failure_event,
)
from app.services.alert_rule_settings_service import get_effective_alert_rule_policy
from app.database import SessionLocal
from app.shared.notification.notification_service import NotificationService

logger = logging.getLogger(__name__)

FAILURE_WARNING_NOTIFY_STATE = "failure_warning"
FAILURE_ALERT_BUCKET_SECONDS = 300
FAILURE_ALERT_MARKER_TABLE_DESIGN = {
    "table": "failure_alert_markers",
    "unique_key": ["source", "entity_id", "failure_kind", "attempt_or_bucket"],
    "columns": ["dedup_key", "first_seen_at", "last_seen_at", "send_count"],
}

_sent_alert_keys: dict[str, float] = {}


def reset_failure_alert_debounce() -> None:
    _sent_alert_keys.clear()


async def report_failure_alert(
    event: FailureEvent,
    *,
    registry=None,
    notification_service_factory: Callable[[], NotificationService] = NotificationService,
    db_session_factory: Callable[[], object] = SessionLocal,
    now: float | None = None,
) -> AlertDecision:
    """Classify and deliver a failure alert without raising delivery errors."""
    decision = classify_failure_event(event, registry=registry)
    policy = _load_effective_policy(event.source, registry=registry, db_session_factory=db_session_factory)
    if policy is not None:
        if policy.stale or not policy.enabled:
            return replace(decision, should_send=False, suppressed_reason="rule_disabled")
        if policy.burst_threshold is not None and (event.count or 0) < policy.burst_threshold:
            return replace(decision, should_send=False, suppressed_reason="burst_threshold")
        if policy.severity_override is not None:
            decision = replace(
                decision,
                severity=policy.severity_override,
                should_send=policy.severity_override in (AlertSeverity.CRITICAL, AlertSeverity.WARNING),
                force_send=policy.severity_override == AlertSeverity.CRITICAL,
            )

    dedup_key = build_failure_alert_dedup_key(event, now=now)
    decision = replace(decision, dedup_key=dedup_key)

    if decision.suppressed_reason == "existing_coverage":
        return decision
    if not decision.should_send:
        return decision

    service = None
    if decision.severity == AlertSeverity.WARNING:
        try:
            service = notification_service_factory()
            if not service.should_notify(FAILURE_WARNING_NOTIFY_STATE):
                return replace(decision, should_send=False, suppressed_reason="warning_opt_out")
        except Exception as exc:
            logger.warning("Failure alert settings check failed: %s", exc)
            return replace(decision, should_send=False, suppressed_reason="warning_settings_error")

    cooldown_seconds = policy.cooldown_seconds if policy is not None else FAILURE_ALERT_BUCKET_SECONDS
    channel = policy.channel if policy is not None else "telegram"
    if channel == "ui_only":
        return replace(decision, should_send=False, suppressed_reason="ui_only")

    if _is_duplicate(dedup_key, now=now, ttl_seconds=cooldown_seconds):
        return replace(decision, should_send=False, suppressed_reason="duplicate")

    message = build_failure_alert_message(event, decision)

    try:
        if service is None:
            service = notification_service_factory()
        if channel == "desktop":
            await service.send_notification_message(
                message,
                send_desktop=True,
                send_telegram=False,
                force_send=decision.force_send,
            )
        elif decision.severity == AlertSeverity.CRITICAL:
            await service.send_telegram(message, force_send=True)
        elif decision.severity == AlertSeverity.WARNING:
            await service.send_telegram(message, force_send=False)
    except Exception as exc:
        logger.warning("Failure alert delivery failed: %s", exc)

    return decision


async def report_video_failure_alert(
    *,
    request_id: str | int,
    failure_kind: str,
    error_summary: str | None = None,
    url: str | None = None,
    attempt: str | int | None = None,
    notification_service_factory: Callable[[], NotificationService] = NotificationService,
) -> AlertDecision:
    """Ready-to-call helper for the video worker integration owner."""
    return await report_failure_alert(
        FailureEvent(
            source="video_downloads",
            entity_id=request_id,
            failure_kind=failure_kind,
            error_summary=error_summary,
            url=url,
            attempt=attempt,
        ),
        notification_service_factory=notification_service_factory,
    )


def _load_effective_policy(event_source: str, *, registry, db_session_factory):
    db = None
    try:
        db = db_session_factory()
        return get_effective_alert_rule_policy(db, event_source, registry=registry)
    except Exception as exc:
        logger.warning("Failure alert rule settings check failed: %s", exc)
        return None
    finally:
        if db is not None:
            close = getattr(db, "close", None)
            if callable(close):
                close()


def build_failure_alert_dedup_key(event: FailureEvent, *, now: float | None = None) -> str:
    entity = str(event.entity_id) if event.entity_id is not None else "-"
    kind = (event.failure_kind or "unknown").strip().lower().replace(" ", "_").replace("-", "_")
    if event.attempt is not None:
        attempt_or_bucket = f"attempt:{event.attempt}"
    else:
        current = time.time() if now is None else now
        attempt_or_bucket = f"bucket:{int(current // FAILURE_ALERT_BUCKET_SECONDS)}"
    return f"{event.source}:{entity}:{kind}:{attempt_or_bucket}"


def _is_duplicate(dedup_key: str, *, now: float | None = None, ttl_seconds: int = FAILURE_ALERT_BUCKET_SECONDS) -> bool:
    current = time.time() if now is None else now
    _expire_old_keys(current, ttl_seconds=ttl_seconds)
    if dedup_key in _sent_alert_keys:
        return True
    _sent_alert_keys[dedup_key] = current
    return False


def _expire_old_keys(current: float, *, ttl_seconds: int = FAILURE_ALERT_BUCKET_SECONDS) -> None:
    ttl = max(ttl_seconds, 1) * 2
    expired = [key for key, seen_at in _sent_alert_keys.items() if current - seen_at > ttl]
    for key in expired:
        _sent_alert_keys.pop(key, None)
