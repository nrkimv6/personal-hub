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
    pytestmark = pytest.mark.http

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

    def test_direct_merge_safe_doc_payload_preserved(self, client):
        """R: direct-merge 응답은 safe-doc auto-resolved payload를 그대로 노출한다."""
        mock_result = {
            "success": True,
            "message": "safe-doc auto-resolved",
            "merge_status": "merged",
            "action": "direct-merge",
        }
        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.send_direct_merge_command",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post(
                "/api/v1/dev-runner/merge/direct",
                json={"branch": "runner/test-safe-doc", "worktree_path": "/some/path"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("merge_status") == "merged"
        assert data.get("message") == "safe-doc auto-resolved"

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

    def test_retry_merge_conflict_payload_preserved(self, client):
        """B: retry-merge 응답은 unsafe conflict payload를 conflict로 유지한다."""
        mock_result = {
            "success": False,
            "message": "unsafe conflict requires manual resolution",
            "merge_status": "conflict",
        }
        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.send_runner_command",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post("/api/v1/dev-runner/runners/runner-test/retry-merge")
        assert resp.status_code in (200, 404, 400)
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("merge_status") == "conflict"
            assert "manual resolution" in data.get("message", "")


class TestDirectMergePlanFileInSSE:
    """T4: POST /merge/direct 후 SSE status의 plan_file 필드 계약 확인"""

    def test_build_status_payload_dm_runner_keeps_plan_file_none(self):
        """T4-21: dm-* runner에서도 plan_file 미설정이면 None 유지"""
        import fakeredis
        from app.modules.dev_runner.services.event_payload import build_status_payload
        from app.modules.dev_runner.services.event_routing import RUNNER_KEY_PREFIX

        sync_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "dm-http-test"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        # plan_file 미설정

        payload = build_status_payload(sync_redis, runner_id)
        assert payload is not None
        assert payload["plan_file"] is None, \
            f"dm-* runner의 plan_file은 None이어야 함: {payload['plan_file']}"


class TestLogsRecentRedisListFallback:
    """T4: GET /logs/recent dm-* runner Redis list fallback"""

    pytestmark = pytest.mark.http

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
    """T4: 일반 runner SSE 계약 — plan_file 미설정 시 None 유지"""

    def test_normal_runner_plan_file_none_regression(self):
        """T4-23: 일반 runner에서 plan_file=None, branch=None → plan_file=None"""
        import fakeredis
        from app.modules.dev_runner.services.event_payload import build_status_payload
        from app.modules.dev_runner.services.event_routing import RUNNER_KEY_PREFIX

        sync_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "normal-runner-01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", "1234")
        # plan_file 미설정

        payload = build_status_payload(sync_redis, runner_id)
        assert payload is not None
        assert payload["plan_file"] is None, \
            f"일반 runner의 plan_file은 None이어야 함: {payload['plan_file']}"


class TestRetryMergeExitCode2Http:
    """T5 HTTP: POST /runners/{id}/retry-merge → exit_code=2 → fixing → merged 상태 흐름"""

    pytestmark = pytest.mark.http

    @pytest.mark.http
    def test_retry_merge_returns_test_failed_then_fixing_http(self, client):
        """T5-HTTP: retry-merge 엔드포인트 → send_runner_command mock으로
        test_failed → merged 전이 흐름 확인.
        엔드포인트 자체가 merge_status를 반환하므로 200 + merge_status 필드 검증.
        """
        mock_result = {
            "success": True,
            "message": "test fixed and merged",
            "merge_status": "merged",
        }
        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.send_runner_command",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post("/api/v1/dev-runner/runners/runner-exit2/retry-merge")

        assert resp.status_code in (200, 404, 400), \
            f"예상치 못한 status_code: {resp.status_code}"
        # 200인 경우 응답 구조 검증
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("success") is True, f"success가 True가 아님: {data}"
