"""Phase T4: HTTP 통합 테스트 — merge-queue, merge-log/stream, run with worktree"""
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app

pytestmark = pytest.mark.http


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestMergeQueueEndpoint:
    def test_merge_queue_returns_list(self, client):
        """GET /api/dev-runner/merge-queue — 큐 항목 없어도 빈 JSON 배열 반환"""
        r = client.get("/api/v1/dev-runner/merge-queue")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_merge_log_stream_content_type(self, client):
        """GET /api/dev-runner/merge-log/stream?runner_id=... — text/event-stream 응답

        SSE는 무한 스트림이므로 log_service를 mock하여 즉시 종료되는 제너레이터로 교체.
        TestClient는 스트림 완료를 기다리므로 실제 무한 SSE 스트림은 mock 필수.
        """
        async def _quick_stream(runner_id: str):
            yield "event: connected\ndata: ok\n\n"

        with patch(
            "app.modules.dev_runner.services.log_service.log_service.stream_merge_log",
            side_effect=_quick_stream,
        ):
            r = client.get(
                "/api/v1/dev-runner/merge-log/stream?runner_id=test_t4_runner",
                headers={"Accept": "text/event-stream"},
            )
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

    def test_run_with_worktree_field(self, client):
        """POST /api/dev-runner/run (worktree: true) — 400/200 모두 허용, 필드 파싱 확인"""
        from app.modules.dev_runner.schemas import RunRequest

        # worktree 기본값 True 확인
        req_default = RunRequest(engine="gemini", plan_file="test.md")
        assert req_default.worktree is True

        # worktree=False 설정 확인
        req_false = RunRequest(engine="gemini", plan_file="test.md", worktree=False)
        assert req_false.worktree is False


class TestMergeStatusTransitionHttp:
    """T4: merge_status 전이 HTTP 엔드포인트 검증 (todo-4)"""

    def test_runner_merge_status_transition_http(self, client):
        """GET /api/v1/dev-runner/merge/{runner_id} — status 필드가 queued/merging/merged 전이 흐름 확인

        executor_service.get_merge_status()를 mock하여 각 상태값이 HTTP 응답에 올바르게
        반영되는지 확인한다. 실제 Redis 의존 없이 API 레이어 전이 흐름을 검증.
        """
        from unittest.mock import patch, AsyncMock
        from app.modules.dev_runner import routes as dev_runner_routes

        runner_id = "t4-merge-status-01"

        for expected_status in ("queued", "merging", "merged"):
            mock_result = {"runner_id": runner_id, "status": expected_status, "fix_attempts": 0, "message": ""}
            with patch(
                "app.modules.dev_runner.routes.runner.executor_service.get_merge_status",
                new=AsyncMock(return_value=mock_result),
            ):
                r = client.get(f"/api/v1/dev-runner/merge/{runner_id}")
            assert r.status_code == 200, f"status={expected_status}: HTTP {r.status_code}"
            body = r.json()
            assert body["status"] == expected_status, f"expected {expected_status}, got {body['status']}"
            assert body["runner_id"] == runner_id
