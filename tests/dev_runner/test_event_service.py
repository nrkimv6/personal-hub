"""event_service._build_status_payload plan_file contract tests.

현재 계약:
- Redis plan_file 키 미설정(None) 또는 빈 문자열("")은 SSE payload에서 None으로 전달한다.
- sentinel/legacy 값은 실제 저장값을 그대로 전달한다.
"""
from unittest.mock import MagicMock, patch

SENTINEL = "__ALL_PLANS__"


def _make_service():
    """DevRunnerEventService 인스턴스 생성 (Redis 목업).

    __new__로 생성하면 __init__이 호출되지 않으므로 실제 Redis 연결 없이
    mock _sync/_async를 직접 주입한다.
    """
    from app.modules.dev_runner.services.event_service import EventService as DevRunnerEventService
    mock_sync = MagicMock()
    mock_async = MagicMock()
    svc = DevRunnerEventService.__new__(DevRunnerEventService)
    svc._sync = mock_sync
    svc._async = mock_async
    return svc


class TestBuildStatusPayloadPlanFileNullDefense:
    """plan_file가 비어있을 때 None으로 정규화되는지 검증."""

    def test_plan_file_none_returns_none(self):
        """Redis plan_file 키 미설정(None) → payload["plan_file"] is None.

        plan_file 키 설정 전 SSE 이벤트 발생 시 None이 유지되어야 한다.
        """
        svc = _make_service()

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

        payload = svc._build_status_payload("test-runner-id")

        assert payload is not None
        assert payload["plan_file"] is None, "plan_file='' -> None 정규화 필요"

    def test_plan_file_with_value_preserved(self):
        """Redis에 plan_file="docs/plan/2026-03-04_test.md" → 그대로 반환 (Right)"""
        svc = _make_service()
        plan = "docs/plan/2026-03-04_test.md"
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-04T00:00:00", plan, "claude", None, None]

        payload = svc._build_status_payload("test-runner-id")

        assert payload is not None
        assert payload["plan_file"] == plan, "실제 plan_file 값은 변환 없이 보존되어야 함"

    def test_plan_file_sentinel_string_preserved(self):
        """Redis에 plan_file="__ALL_PLANS__" → sentinel 그대로 반환 (Right)"""
        svc = _make_service()
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-04T00:00:00", SENTINEL, "claude", None, None]

        payload = svc._build_status_payload("test-runner-id")

        assert payload is not None
        assert payload["plan_file"] == SENTINEL

    def test_plan_file_legacy_ALL_preserved(self):
        """Redis에 기존 plan_file="ALL" → "ALL" 그대로 반환 (하위 호환, Right)

        event_service는 값을 변환하지 않고 그대로 전달함 — 변환은 비교 시점에만.
        """
        svc = _make_service()
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-04T00:00:00", "ALL", "claude", None, None]

        payload = svc._build_status_payload("test-runner-id")

        assert payload is not None
        # "ALL"은 falsy가 아니므로 그대로 반환됨 (event_service는 변환 책임 없음)
        assert payload["plan_file"] == "ALL"


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
