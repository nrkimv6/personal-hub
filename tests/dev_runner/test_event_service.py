"""event_service._build_status_payload plan_file null 방어 테스트

RIGHT-BICEP: Error 케이스 — Redis에 plan_file 키가 없는 runner가 SSE payload에
"ALL" fallback을 반환하는지 검증.
"""
from unittest.mock import MagicMock, patch


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
    """plan_file=None → "ALL" fallback 방어 테스트"""

    def test_plan_file_none_returns_ALL(self):
        """Redis에 plan_file 키 없을 때(None) → payload["plan_file"] == "ALL"

        Error 케이스: plan_file 키 설정 전 SSE 이벤트가 발생하면 None이 반환되는 상황.
        """
        svc = _make_service()

        # mget: [status, pid, current_cycle, start_time, plan_file=None, engine]
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-04T00:00:00", None, "claude"]

        payload = svc._build_status_payload("test-runner-id")

        assert payload is not None
        assert payload["plan_file"] == "ALL", "plan_file=None → 'ALL' fallback 필요"

    def test_plan_file_empty_string_returns_ALL(self):
        """Redis에 plan_file=""(빈 문자열) → payload["plan_file"] == "ALL"

        Boundary 케이스: 빈 문자열도 falsy이므로 "ALL"로 변환되어야 함.
        """
        svc = _make_service()
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-04T00:00:00", "", "claude"]

        payload = svc._build_status_payload("test-runner-id")

        assert payload is not None
        assert payload["plan_file"] == "ALL", "plan_file='' → 'ALL' fallback 필요"

    def test_plan_file_with_value_preserved(self):
        """Redis에 plan_file="docs/plan/2026-03-04_test.md" → 그대로 반환 (Right)"""
        svc = _make_service()
        plan = "docs/plan/2026-03-04_test.md"
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-04T00:00:00", plan, "claude"]

        payload = svc._build_status_payload("test-runner-id")

        assert payload is not None
        assert payload["plan_file"] == plan, "실제 plan_file 값은 변환 없이 보존되어야 함"

    def test_plan_file_ALL_string_preserved(self):
        """Redis에 plan_file="ALL" → "ALL" 그대로 반환 (Right)"""
        svc = _make_service()
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-04T00:00:00", "ALL", "claude"]

        payload = svc._build_status_payload("test-runner-id")

        assert payload is not None
        assert payload["plan_file"] == "ALL"
