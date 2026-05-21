"""Failure alert delivery tests."""

from unittest.mock import AsyncMock

import pytest

from app.services.failure_alert_delivery import (
    FAILURE_WARNING_NOTIFY_STATE,
    build_failure_alert_dedup_key,
    report_failure_alert,
    reset_failure_alert_debounce,
)
from app.services.failure_alert_policy import FailureEvent


class FakeNotificationService:
    def __init__(self, *, should_notify=True, raise_on_send=False):
        self.should_notify_value = should_notify
        self.send_telegram = AsyncMock(side_effect=RuntimeError("telegram down") if raise_on_send else None)

    def should_notify(self, state: str) -> bool:
        assert state == FAILURE_WARNING_NOTIFY_STATE
        return self.should_notify_value


@pytest.mark.asyncio
async def test_report_failure_alert_right_force_sends_critical():
    reset_failure_alert_debounce()
    service = FakeNotificationService()

    decision = await report_failure_alert(
        FailureEvent(source="worker_orchestrator", entity_id="worker-a", failure_kind="worker_permanent_failure"),
        notification_service_factory=lambda: service,
        now=1000.0,
    )

    assert decision.should_send is True
    assert decision.force_send is True
    service.send_telegram.assert_awaited_once()
    assert service.send_telegram.call_args.kwargs["force_send"] is True


@pytest.mark.asyncio
async def test_report_failure_alert_error_telegram_exception_does_not_raise():
    reset_failure_alert_debounce()
    service = FakeNotificationService(raise_on_send=True)

    decision = await report_failure_alert(
        FailureEvent(source="google_search_queue", entity_id=1, failure_kind="captcha_terminal"),
        notification_service_factory=lambda: service,
        now=1001.0,
    )

    assert decision.force_send is True
    service.send_telegram.assert_awaited_once()


@pytest.mark.asyncio
async def test_report_failure_alert_cardinality_dedup_same_attempt_once():
    reset_failure_alert_debounce()
    service = FakeNotificationService()
    event = FailureEvent(
        source="worker_orchestrator",
        entity_id="worker-a",
        failure_kind="worker_permanent_failure",
        attempt="same",
    )

    first = await report_failure_alert(event, notification_service_factory=lambda: service, now=1002.0)
    second = await report_failure_alert(event, notification_service_factory=lambda: service, now=1003.0)

    assert first.suppressed_reason is None
    assert second.suppressed_reason == "duplicate"
    assert service.send_telegram.await_count == 1


@pytest.mark.asyncio
async def test_report_failure_alert_warning_respects_opt_in_state():
    reset_failure_alert_debounce()
    service = FakeNotificationService(should_notify=False)

    decision = await report_failure_alert(
        FailureEvent(source="file_search_requests", failure_kind="everything_unavailable"),
        notification_service_factory=lambda: service,
        now=1004.0,
    )

    assert decision.suppressed_reason == "warning_opt_out"
    service.send_telegram.assert_not_awaited()


def test_build_failure_alert_dedup_key_boundary_same_bucket():
    event = FailureEvent(source="file_search_requests", entity_id="tool", failure_kind="everything_unavailable")

    assert build_failure_alert_dedup_key(event, now=1000.0) == build_failure_alert_dedup_key(event, now=1099.0)
