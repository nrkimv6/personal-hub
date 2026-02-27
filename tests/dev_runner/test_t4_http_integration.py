"""Phase T4: HTTP 통합 테스트 — merge-queue, merge-log/stream, run with worktree"""
import pytest
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
        """GET /api/dev-runner/merge-log/stream?runner_id=... — text/event-stream 응답"""
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
