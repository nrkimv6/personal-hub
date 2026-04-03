"""EventService 상태 payload 단위 테스트."""

from unittest.mock import MagicMock


def _make_service():
    from app.modules.dev_runner.services.event_service import EventService

    svc = EventService.__new__(EventService)
    svc._sync = MagicMock()
    svc._async = MagicMock()
    return svc


class TestBuildStatusPayloadPlanFile:
    def test_plan_file_none_returns_none(self):
        svc = _make_service()
        svc._sync.mget.return_value = [
            "running",
            "1234",
            "1",
            "2026-03-04T00:00:00",
            None,
            "claude",
            None,
            "user",
            None,
            None,
        ]

        payload = svc._build_status_payload("runner-a")

        assert payload is not None
        assert payload["plan_file"] is None

    def test_plan_file_empty_string_returns_none(self):
        svc = _make_service()
        svc._sync.mget.return_value = [
            "running",
            "1234",
            "1",
            "2026-03-04T00:00:00",
            "",
            "claude",
            None,
            "user",
            None,
            None,
        ]

        payload = svc._build_status_payload("runner-b")

        assert payload is not None
        assert payload["plan_file"] is None

    def test_plan_file_with_value_preserved(self):
        svc = _make_service()
        svc._sync.mget.return_value = [
            "running",
            "1234",
            "1",
            "2026-03-04T00:00:00",
            "docs/plan/test.md",
            "claude",
            None,
            "user",
            None,
            None,
        ]

        payload = svc._build_status_payload("runner-c")

        assert payload is not None
        assert payload["plan_file"] == "docs/plan/test.md"


class TestBuildStatusPayloadVisible:
    def test_visible_true_for_user_trigger(self):
        svc = _make_service()
        svc._sync.mget.return_value = [
            "running",
            "1234",
            "1",
            "2026-03-04T00:00:00",
            "docs/plan/test.md",
            "claude",
            None,
            "user",
            None,
            None,
        ]

        payload = svc._build_status_payload("runner-user")

        assert payload is not None
        assert payload["visible"] is True

    def test_visible_false_for_api_trigger(self):
        svc = _make_service()
        svc._sync.mget.return_value = [
            "running",
            "1234",
            "1",
            "2026-03-04T00:00:00",
            "docs/plan/test.md",
            "claude",
            None,
            "api",
            None,
            None,
        ]

        payload = svc._build_status_payload("runner-api")

        assert payload is not None
        assert payload["visible"] is False

    def test_visible_false_for_tc_prefix_even_user_trigger(self):
        svc = _make_service()
        svc._sync.mget.return_value = [
            "running",
            "1234",
            "1",
            "2026-03-04T00:00:00",
            "docs/plan/test.md",
            "claude",
            None,
            "user",
            None,
            None,
        ]

        payload = svc._build_status_payload("tc-pytest-abc123")

        assert payload is not None
        assert payload["visible"] is False
