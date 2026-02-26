"""
HTTP 레벨 통합 테스트: Merge Queue API (TestClient)
"""
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"


@pytest.fixture(scope="module")
def api_client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def mock_executor_merge_queue():
    """get_merge_queue()를 mock하여 fakeredis 없이 HTTP 계층 테스트"""
    return []


def make_queue_item_dict(runner_id: str = "abc12345", status: str = "pending") -> dict:
    return {
        "runner_id": runner_id,
        "branch": f"runner/{runner_id}",
        "worktree_path": "",
        "plan_file": "/work/docs/plan/test.md",
        "project": "monitor-page",
        "timestamp": "2026-02-26T10:00:00",
        "status": status,
    }


class TestMergeQueueHTTP:
    def test_http1_get_merge_queue_returns_list(self, api_client):
        """HTTP-1: GET /merge-queue → 200, list 형식"""
        item = make_queue_item_dict()

        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=[item])
        ):
            resp = api_client.get(f"{BASE_URL}/merge-queue")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_http2_empty_queue_returns_empty_list(self, api_client):
        """HTTP-2: GET /merge-queue (빈 큐) → 200, []"""
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=[])
        ):
            resp = api_client.get(f"{BASE_URL}/merge-queue")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_http3_get_merge_status_existing_runner(self, api_client):
        """HTTP-3: GET /merge/{runner_id} → 200, MergeStatusResponse 스키마"""
        status_dict = {
            "runner_id": "abc12345",
            "status": "testing",
            "test_passed": None,
            "fix_attempts": 0,
            "message": "",
        }

        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_status",
            new=AsyncMock(return_value=status_dict)
        ):
            resp = api_client.get(f"{BASE_URL}/merge/abc12345")

        assert resp.status_code == 200
        data = resp.json()
        assert data["runner_id"] == "abc12345"
        assert data["status"] == "testing"

    def test_http4_get_merge_status_nonexistent_returns_404(self, api_client):
        """HTTP-4: GET /merge/nonexistent → 404"""
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_status",
            new=AsyncMock(return_value=None)
        ):
            resp = api_client.get(f"{BASE_URL}/merge/nonexistent")

        assert resp.status_code == 404

    def test_http5_retry_merge_returns_200(self, api_client):
        """HTTP-5: POST /merge/{runner_id}/retry → 200"""
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.send_runner_command",
            new=AsyncMock(return_value={"success": True, "message": "retry-merge sent"})
        ):
            resp = api_client.post(f"{BASE_URL}/merge/abc12345/retry")

        assert resp.status_code == 200

    def test_http6_revert_merge_returns_200(self, api_client):
        """HTTP-6: POST /merge/{runner_id}/revert → 200"""
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.send_runner_command",
            new=AsyncMock(return_value={"success": True, "message": "revert-merge sent"})
        ):
            resp = api_client.post(f"{BASE_URL}/merge/abc12345/revert")

        assert resp.status_code == 200

    def test_http7_schema_validation_merge_queue_item(self, api_client):
        """HTTP-7: 스키마 검증 — MergeQueueItem 필드 타입"""
        from app.modules.dev_runner.schemas import MergeQueueItem

        item = MergeQueueItem(
            runner_id="abc12345",
            branch="runner/abc12345",
            plan_file="/work/plan.md",
            project="monitor-page",
            status="pending",
            timestamp="2026-02-26T10:00:00",
            worktree_path="",
        )
        assert isinstance(item.runner_id, str)
        assert isinstance(item.status, str)

    def test_http7_schema_validation_merge_status_response(self, api_client):
        """HTTP-7: 스키마 검증 — MergeStatusResponse 필드 타입"""
        from app.modules.dev_runner.schemas import MergeStatusResponse

        resp = MergeStatusResponse(
            runner_id="abc12345",
            status="done",
            test_passed=True,
            fix_attempts=1,
            message="완료",
        )
        assert isinstance(resp.runner_id, str)
        assert isinstance(resp.fix_attempts, int)
        assert resp.test_passed is True

    def test_http1_queue_item_contains_required_fields(self, api_client):
        """HTTP-1 보충: 각 항목에 runner_id, branch, plan_file, status 포함"""
        item = make_queue_item_dict("r001")

        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=[item])
        ):
            resp = api_client.get(f"{BASE_URL}/merge-queue")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        first = data[0]
        for key in ("runner_id", "branch", "plan_file", "status"):
            assert key in first, f"필드 누락: {key}"
