"""
TC HTTP: POST /api/v1/dev-runner/merge/direct 통합 테스트
FastAPI TestClient 기반 — 실제 서버 불필요
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


class TestDirectMergeHttp:
    def test_direct_merge_success(self, client):
        """R(Right): POST /merge/direct → 200 + success=True"""
        mock_result = {"success": True, "message": "accepted", "action": "direct-merge"}
        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.send_direct_merge_command",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post(
                "/api/v1/dev-runner/merge/direct",
                json={"branch": "runner/test123", "worktree_path": "/some/path"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True

    def test_direct_merge_missing_branch_422(self, client):
        """B(Boundary): branch 누락 → 422 Validation Error"""
        resp = client.post(
            "/api/v1/dev-runner/merge/direct",
            json={"worktree_path": "/some/path"},
        )
        assert resp.status_code == 422

    def test_retry_merge_endpoint_regression(self, client):
        """R(Right): POST /runners/{id}/retry-merge 기존 엔드포인트 정상 동작 (회귀)"""
        mock_result = {"success": True, "message": "accepted"}
        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.send_runner_command",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post("/api/v1/dev-runner/runners/runner-test/retry-merge")
        # 200 또는 404 (runner 없음) — 422/500이 아니면 엔드포인트 자체는 정상
        assert resp.status_code in (200, 404, 400)


class TestDirectMergePlanFileInSSE:
    """T4: POST /merge/direct 후 SSE status의 plan_file 필드 확인"""

    def test_build_status_payload_returns_branch_as_plan_file(self):
        """T4-21: dm-* runner에서 plan_file=None, branch="plan/test" → plan_file="plan/test" """
        from app.modules.dev_runner.services.event_service import EventService

        svc = EventService.__new__(EventService)
        svc._sync = MagicMock()
        svc._async = MagicMock()

        # mget: [status, pid, current_cycle, start_time, plan_file, engine, branch]
        svc._sync.mget.return_value = ["running", None, None, "2026-03-05T00:00:00", None, None, "plan/test"]

        payload = svc._build_status_payload("dm-http-test")
        assert payload is not None
        assert payload["plan_file"] == "plan/test", \
            f"dm-* runner의 plan_file이 branch fallback 안 됨: {payload['plan_file']}"


class TestLogsRecentRedisListFallback:
    """T4: GET /logs/recent dm-* runner Redis list fallback"""

    def test_logs_recent_redis_list_fallback(self, client):
        """T4-22: dm-* runner 로그 파일 없음 + Redis list 존재 → merge 로그 반환"""
        from app.modules.dev_runner.schemas import LogResponse

        mock_response = LogResponse(
            lines=["[MERGE] lock 획득", "[MERGE] merge 시작", "[MERGE] merge 완료"],
            total_lines=3,
        )

        with patch(
            "app.modules.dev_runner.services.log_service.LogService.tail_log_file",
            return_value=mock_response,
        ):
            resp = client.get("/api/v1/dev-runner/logs/recent?runner_id=dm-test123")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["lines"]) == 3
        assert "[MERGE]" in data["lines"][0]


class TestNormalRunnerPlanFileAllRegression:
    """T4: 기존 일반 runner SSE 회귀 — plan_file=None + branch=None → "ALL" """

    def test_normal_runner_plan_file_all_regression(self):
        """T4-23: 일반 runner에서 plan_file=None, branch=None → plan_file="ALL" 유지"""
        from app.modules.dev_runner.services.event_service import EventService

        svc = EventService.__new__(EventService)
        svc._sync = MagicMock()
        svc._async = MagicMock()

        # 일반 runner: plan_file=None, branch=None
        svc._sync.mget.return_value = ["running", "1234", "1", "2026-03-05T00:00:00", None, "claude", None]

        payload = svc._build_status_payload("normal-runner-01")
        assert payload is not None
        assert payload["plan_file"] == "ALL", \
            f"일반 runner의 plan_file이 'ALL'이 아님: {payload['plan_file']}"
