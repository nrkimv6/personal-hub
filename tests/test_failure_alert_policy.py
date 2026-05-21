"""Failure alert policy classification tests."""

from app.services.failure_alert_policy import (
    AlertSeverity,
    FailureEvent,
    build_failure_alert_message,
    classify_failure_event,
)


def test_classify_failure_event_right_critical_sources():
    cases = [
        FailureEvent(source="worker_orchestrator", failure_kind="worker_permanent_failure"),
        FailureEvent(source="video_downloads", failure_kind="youtube_stream_ffmpeg"),
        FailureEvent(source="video_downloads", failure_kind="youtube_live_ffmpeg_failed"),
        FailureEvent(source="google_search_queue", failure_kind="captcha_terminal"),
        FailureEvent(source="task_schedule_runs", failure_kind="stale_cleanup_burst", count=3),
    ]

    for event in cases:
        decision = classify_failure_event(event)
        assert decision.severity == AlertSeverity.CRITICAL
        assert decision.should_send is True
        assert decision.force_send is True


def test_classify_failure_event_boundary_unknown_source_record_only():
    decision = classify_failure_event(FailureEvent(source="unknown_source", error_summary=""))

    assert decision.severity == AlertSeverity.RECORD_ONLY
    assert decision.should_send is False


def test_classify_failure_event_error_access_restriction_record_only():
    cases = [
        FailureEvent(source="crawl_requests", failure_kind="instagram_account_missing"),
        FailureEvent(source="crawl_requests", failure_kind="access_restriction", error_summary="Private"),
        FailureEvent(source="video_downloads", failure_kind="youtube_live_access_restricted"),
        FailureEvent(source="video_downloads", failure_kind="vod_404", error_summary="404 not found"),
        FailureEvent(source="video_downloads", failure_kind="user_cancelled"),
    ]

    for event in cases:
        decision = classify_failure_event(event)
        assert decision.severity == AlertSeverity.RECORD_ONLY
        assert decision.should_send is False


def test_classify_failure_event_reference_existing_coverage_suppressed():
    decision = classify_failure_event(
        FailureEvent(source="operational_issue", failure_kind="database_down")
    )

    assert decision.suppressed_reason == "existing_coverage"
    assert decision.should_send is False


def test_build_failure_alert_message_right_includes_entity_and_summary():
    event = FailureEvent(
        source="google_search_queue",
        entity_id=42,
        failure_kind="captcha_terminal",
        error_summary="CAPTCHA 감지됨. 수동 해결이 필요합니다.",
        url="https://example.test/search",
    )
    decision = classify_failure_event(event)

    message = build_failure_alert_message(event, decision)

    assert "source: google_search_queue" in message
    assert "entity_id: 42" in message
    assert "failure_kind: captcha_terminal" in message
    assert "CAPTCHA" in message
    assert "https://example.test/search" in message
