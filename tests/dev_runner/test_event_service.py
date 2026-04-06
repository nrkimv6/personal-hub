"""event_service._build_status_payload plan_file contract tests.

현재 계약:
- Redis plan_file 키 미설정(None) 또는 빈 문자열("")은 SSE payload에서 None으로 전달한다.
- sentinel/legacy 값은 실제 저장값을 그대로 전달한다.
"""
from unittest.mock import MagicMock, patch

SENTINEL = "__ALL_PLANS__"


def _make_service():
    from app.modules.dev_runner.services.event_service import EventService

    svc = EventService.__new__(EventService)
    svc._sync = MagicMock()
    svc._async = MagicMock()
    return svc


class TestBuildStatusPayloadPlanFileNullDefense:
    """plan_file가 비어있을 때 None으로 정규화되는지 검증."""

    def test_plan_file_none_returns_none(self):
        """Redis plan_file 키 미설정(None) → payload["plan_file"] is None.

        plan_file 키 설정 전 SSE 이벤트 발생 시 None이 유지되어야 한다.
        """
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

        # mget: [status, pid, current_cycle, start_time, plan_file, engine, branch, trigger]
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-04T00:00:00", None, "claude", None, None]

        payload = svc._build_status_payload("test-runner-id")

        assert payload is not None
        assert payload["plan_file"] is None, "plan_file=None -> None 유지 필요"

    def test_plan_file_empty_string_returns_none(self):
        """Redis plan_file=""(빈 문자열) -> payload["plan_file"] is None.

        Boundary 케이스: 빈 문자열도 없음으로 간주한다.
        """
        svc = _make_service()
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-04T00:00:00", "", "claude", None, None]

        payload = svc._build_status_payload("runner-b")

        assert payload is not None
        assert payload["plan_file"] is None, "plan_file='' -> None 정규화 필요"

    def test_plan_file_with_value_preserved(self):
        svc = _make_service()
        plan = "docs/plan/2026-03-04_test.md"
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-04T00:00:00", plan, "claude", None, None]

        payload = svc._build_status_payload("runner-c")

        assert payload is not None
        assert payload["plan_file"] == plan


class TestBuildStatusPayloadVisible:
    def test_visible_true_for_user_trigger(self):
        svc = _make_service()
        svc._sync.mget.return_value = [
            "running",
            "1234",
            "1",
            "2026-03-04T00:00:00",
            SENTINEL,
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
            "ALL",
            "claude",
            None,
            "api",
            None,
            None,
        ]

        payload = svc._build_status_payload("runner-api")

        assert payload is not None
        assert payload["visible"] is False


class TestBuildStatusPayloadBranchHandling:
    """branch 값이 있어도 plan_file 미설정이면 None 유지."""

    def test_dm_runner_branch_does_not_override_plan_file(self):
        """plan_file=None, branch="plan/test" -> plan_file is None."""
        svc = _make_service()
        svc._sync.mget.return_value = ["running", None, None, "2026-03-04T00:00:00", None, None, "plan/test", None]
        payload = svc._build_status_payload("dm-abc123")
        assert payload is not None
        assert payload["plan_file"] is None

    def test_normal_runner_no_branch_returns_none(self):
        """plan_file=None, branch=None -> plan_file is None."""
        svc = _make_service()
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-04T00:00:00", None, "claude", None, None]
        payload = svc._build_status_payload("normal-runner")
        assert payload is not None
        assert payload["plan_file"] is None


class TestBuildStatusPayloadExecutionCount:
    """execution_count 필드가 SSE payload에 포함되는지 검증 (Phase T1)."""

    def test_execution_count_included_when_set(self):
        """R: Redis execution_count=2 → payload["execution_count"] == "2"."""
        svc = _make_service()
        # 11 fields: status, pid, current_cycle, start_time, plan_file, engine, branch, trigger, exit_reason, error, execution_count
        svc._sync.mget.return_value = [
            "running", "1234", "1", "2026-03-04T00:00:00",
            "docs/plan/test.md", "claude", None, "user",
            None, None, "2",
        ]
        payload = svc._build_status_payload("runner-ec")
        assert payload is not None
        assert payload["execution_count"] == "2"

    def test_execution_count_none_when_not_set(self):
        """B: Redis execution_count 미설정(None) → payload["execution_count"] is None."""
        svc = _make_service()
        svc._sync.mget.return_value = [
            "running", "1234", "1", "2026-03-04T00:00:00",
            "docs/plan/test.md", "claude", None, "user",
            None, None, None,
        ]
        payload = svc._build_status_payload("runner-no-ec")
        assert payload is not None
        assert payload.get("execution_count") is None
