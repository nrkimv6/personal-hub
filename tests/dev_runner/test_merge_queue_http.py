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


def make_queue_item_dict(runner_id: str = "t-mqhttp-abc1", status: str = "pending") -> dict:
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
            "runner_id": "t-mqhttp-abc1",
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
        assert data["runner_id"] == "t-mqhttp-abc1"
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
            runner_id="t-mqhttp-abc1",
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
            runner_id="t-mqhttp-abc1",
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

    # ── Phase T4 신규 TC ────────────────────────────────────────────────────

    def test_http_post_retry_merge_with_plan_file(self, api_client):
        """T4-28: POST /merge/{runner_id}/retry → send_runner_command에 retry-merge 명령 전달, 200 응답"""
        captured = {}

        async def mock_send(runner_id, command, **kwargs):
            captured["runner_id"] = runner_id
            captured["command"] = command
            return {"success": True, "message": "retry-merge sent"}

        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.send_runner_command",
            new=mock_send
        ):
            resp = api_client.post(f"{BASE_URL}/merge/plan_runner_001/retry")

        assert resp.status_code == 200
        assert captured.get("runner_id") == "plan_runner_001"
        assert captured.get("command") == "retry-merge"

    def test_http_get_merge_queue_item_has_plan_branch_field(self, api_client):
        """T4-29: GET /merge-queue 응답의 branch 필드가 plan/{stem} 형태 반환 검증"""
        item = make_queue_item_dict("r002")
        item["branch"] = "plan/2026-02-27_foo-bar"  # plan/ 접두사

        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=[item])
        ):
            resp = api_client.get(f"{BASE_URL}/merge-queue")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        branch = data[0]["branch"]
        assert branch.startswith("plan/"), f"branch가 plan/ 아님: {branch}"

    def test_http_get_merge_status_reflects_actual_state(self, api_client):
        """T4-30: GET /merge/{id} → status 필드가 mock 반환값과 일치 검증"""
        for status_val in ("conflict", "merged", "testing", "failed"):
            status_dict = {
                "runner_id": "chk_runner",
                "status": status_val,
                "test_passed": None,
                "fix_attempts": 0,
                "message": "",
            }
            with patch(
                "app.modules.dev_runner.services.executor_service.executor_service.get_merge_status",
                new=AsyncMock(return_value=status_dict)
            ):
                resp = api_client.get(f"{BASE_URL}/merge/chk_runner")

            assert resp.status_code == 200
            assert resp.json()["status"] == status_val, f"status 불일치: {status_val}"

    # ── Pipeline E2E HTTP TC ─────────────────────────────────────────────

    def test_h1_post_run_worktree_returns_accepted(self, api_client):
        """H1: POST /run (worktree=true) → runner_id 포함 응답"""
        mock_response = {
            "running": True,
            "engine": "claude",
            "listener_alive": True,
            "redis_connected": True,
            "pid": 12345,
            "plan_file": "docs/plan/test.md",
            "runner_id": "h1_runner",
        }

        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.start_dev_runner",
            new=AsyncMock(return_value=mock_response)
        ):
            resp = api_client.post(f"{BASE_URL}/run", json={
                "plan_file": "docs/plan/test.md",
                "worktree": True,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["runner_id"] == "h1_runner"

    def test_h2_merge_queue_status_polling(self, api_client):
        """H2: GET /merge-queue 폴링 → status 변화 추적"""
        # 1차: pending
        pending_item = make_queue_item_dict("h2_runner", status="pending")
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=[pending_item])
        ):
            resp1 = api_client.get(f"{BASE_URL}/merge-queue")
        assert resp1.json()[0]["status"] == "pending"

        # 2차: merging
        merging_item = make_queue_item_dict("h2_runner", status="merging")
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=[merging_item])
        ):
            resp2 = api_client.get(f"{BASE_URL}/merge-queue")
        assert resp2.json()[0]["status"] == "merging"

        # 3차: done
        done_item = make_queue_item_dict("h2_runner", status="done")
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=[done_item])
        ):
            resp3 = api_client.get(f"{BASE_URL}/merge-queue")
        assert resp3.json()[0]["status"] == "done"

    def test_h3_retry_then_status_change(self, api_client):
        """H3: POST /merge/{id}/retry 후 GET /merge/{id} → status 변화"""
        # retry 요청
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.send_runner_command",
            new=AsyncMock(return_value={"success": True, "message": "retry-merge sent"})
        ):
            resp_retry = api_client.post(f"{BASE_URL}/merge/h3_runner/retry")
        assert resp_retry.status_code == 200

        # status 변경 확인
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_status",
            new=AsyncMock(return_value={
                "runner_id": "h3_runner",
                "status": "merging",
                "test_passed": None,
                "fix_attempts": 0,
                "message": "retry in progress",
            })
        ):
            resp_status = api_client.get(f"{BASE_URL}/merge/h3_runner")
        assert resp_status.status_code == 200
        assert resp_status.json()["status"] == "merging"
