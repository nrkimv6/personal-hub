"""
HTTP 레벨 통합 테스트: Merge Queue API (TestClient)
"""
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock

pytestmark = pytest.mark.http

# ── v2 3-source merge queue ────────────────────────────────────────────────


@pytest.fixture(scope="module")
def api_client_e2e():
    from app.main import app
    return TestClient(app)


@pytest.mark.e2e
class TestMergeQueueV2E2E:
    """T4: TestClient + mock Redis → 3-source 통합 반환 E2E"""

    def test_merge_queue_v2_e2e_active_and_done(self, api_client_e2e):
        """merging/queued/done 항목이 통합 반환되는지 E2E 검증"""
        merged = [
            {"runner_id": "r-merging", "branch": "runner/r-merging", "worktree_path": "",
             "plan_file": "/work/plan.md", "project": "test", "timestamp": "2026-03-30T10:00:00", "status": "merging"},
            {"runner_id": "r-queued", "branch": "runner/r-queued", "worktree_path": "",
             "plan_file": "/work/plan.md", "project": "test", "timestamp": "2026-03-30T10:00:00", "status": "queued"},
            {"runner_id": "r-done", "branch": "runner/r-done", "worktree_path": "",
             "plan_file": "/work/plan.md", "project": "test", "timestamp": "2026-03-30T09:00:00", "status": "done"},
        ]
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=merged)
        ):
            resp = api_client_e2e.get("/api/v1/dev-runner/merge-queue")
        assert resp.status_code == 200
        data = resp.json()
        statuses = [i["status"] for i in data]
        assert "merging" in statuses
        assert "queued" in statuses
        assert "done" in statuses

    def test_merge_queue_v2_e2e_empty(self, api_client_e2e):
        """Redis에 관련 키 없을 때 빈 배열 반환 E2E 확인"""
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=[])
        ):
            resp = api_client_e2e.get("/api/v1/dev-runner/merge-queue")
        assert resp.status_code == 200
        assert resp.json() == []


class TestMergeQueueHTTPV2:
    """T5: HTTP 통합 — v2 3-source merge queue 스키마 검증"""

    def test_merge_queue_http_v2_merging_status(self, api_client):
        """merging runner가 status='merging'으로 반환"""
        item = make_queue_item_dict("v2-runner-01", status="merging")
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=[item])
        ):
            resp = api_client.get("/api/v1/dev-runner/merge-queue")
        assert resp.status_code == 200
        assert resp.json()[0]["status"] == "merging"

    def test_merge_queue_http_v2_mixed_statuses(self, api_client):
        """merging + queued + done 혼합 상태에서 HTTP 응답 스키마 검증"""
        items = [
            make_queue_item_dict("v2-r1", status="merging"),
            make_queue_item_dict("v2-r2", status="queued"),
            make_queue_item_dict("v2-r3", status="done"),
        ]
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=items)
        ):
            resp = api_client.get("/api/v1/dev-runner/merge-queue")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        assert {i["status"] for i in data} == {"merging", "queued", "done"}

    def test_merge_queue_http_v2_backward_compat(self, api_client):
        """기존 MergeQueueItem 응답 필드 유지 확인"""
        item = make_queue_item_dict("v2-compat", status="merging")
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=AsyncMock(return_value=[item])
        ):
            resp = api_client.get("/api/v1/dev-runner/merge-queue")
        assert resp.status_code == 200
        row = resp.json()[0]
        for field in ("runner_id", "branch", "plan_file", "project", "status", "timestamp"):
            assert field in row, f"필드 누락: {field}"

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


# ---------------------------------------------------------------------------
# Phase T4: get_merge_status E2E + POST /merge-queue route 제거 확인
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestMergeStatusE2E:
    """T4: get_merge_status 올바른 키 반환 + enqueue route 제거 E2E"""

    def test_get_merge_status_e2e_returns_status(self, api_client_e2e):
        """GET /merge/{rid} — get_merge_status mock dict 반환 시 200"""
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_status",
            new=AsyncMock(return_value={
                "runner_id": "e2e-rid",
                "status": "merged",
                "test_passed": True,
                "fix_attempts": 0,
                "message": "",
            })
        ):
            resp = api_client_e2e.get("/api/v1/dev-runner/merge/e2e-rid")
        assert resp.status_code == 200
        assert resp.json()["status"] == "merged"
        assert resp.json()["runner_id"] == "e2e-rid"

    def test_get_merge_status_e2e_404_when_missing(self, api_client_e2e):
        """GET /merge/{rid} — get_merge_status None 반환 시 404"""
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_status",
            new=AsyncMock(return_value=None)
        ):
            resp = api_client_e2e.get("/api/v1/dev-runner/merge/missing-runner")
        assert resp.status_code == 404

    def test_post_merge_queue_route_removed(self, api_client_e2e):
        """POST /merge-queue route가 제거되어 404/405 반환"""
        resp = api_client_e2e.post("/api/v1/dev-runner/merge-queue")
        assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Phase T5: get_merge_status HTTP 통합 TC
# ---------------------------------------------------------------------------

class TestMergeStatusHTTP:
    """T5: GET /merge/{rid} HTTP 통합 TC (http marker via pytestmark)"""

    def test_merge_status_http_correct_key(self, api_client):
        """GET /merge/{rid} HTTP — mock dict 반환 시 status 필드 검증"""
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_status",
            new=AsyncMock(return_value={
                "runner_id": "http-runner",
                "status": "merging",
                "test_passed": None,
                "fix_attempts": 1,
                "message": "",
            })
        ):
            resp = api_client.get(f"{BASE_URL}/merge/http-runner")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "merging"
        assert data["runner_id"] == "http-runner"
        assert "test_passed" in data
        assert "fix_attempts" in data

    def test_merge_status_http_not_found(self, api_client):
        """GET /merge/{rid} HTTP — mock None 반환 시 404"""
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_status",
            new=AsyncMock(return_value=None)
        ):
            resp = api_client.get(f"{BASE_URL}/merge/no-runner")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Phase T5: merge-queue-length API TC (신규 — 2026-03-30)
# ---------------------------------------------------------------------------

class TestMergeQueueLengthHTTP:
    """T5: GET /merge-queue-length — 순수 대기 수 반환 (실행 중 제외)"""

    def test_get_merge_queue_length_api(self, api_client):
        """LLEN=3 (1 merging + 2 queued) → {"length": 2}, status 200

        get_merge_queue_length()는 max(0, LLEN-1) 합산이므로
        LLEN=3인 큐 1개 → length=2 반환.
        """
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue_length",
            new=AsyncMock(return_value=2)
        ):
            resp = api_client.get(f"{BASE_URL}/merge-queue-length")

        assert resp.status_code == 200
        data = resp.json()
        assert data == {"length": 2}, f"응답 불일치: {data}"

    def test_get_merge_queue_length_empty_api(self, api_client):
        """큐 비어있을 때 → {"length": 0}, status 200"""
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue_length",
            new=AsyncMock(return_value=0)
        ):
            resp = api_client.get(f"{BASE_URL}/merge-queue-length")

        assert resp.status_code == 200
        data = resp.json()
        assert data == {"length": 0}, f"응답 불일치: {data}"

    def test_get_merge_queue_length_single_merging_api(self, api_client):
        """LLEN=1 (1 merging, 0 queued) → {"length": 0}, status 200

        max(0, 1-1) = 0 이므로 대기 수는 0.
        """
        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue_length",
            new=AsyncMock(return_value=0)
        ):
            resp = api_client.get(f"{BASE_URL}/merge-queue-length")

        assert resp.status_code == 200
        data = resp.json()
        assert data == {"length": 0}, f"응답 불일치: {data}"

    def test_get_merge_queue_api_single_scan_pattern(self, api_client):
        """GET /merge-queue → scan_iter 호출 패턴이 plan-runner:merge-queue:* 1종만 사용

        executor_service.get_merge_queue()가 scan_iter를 호출할 때
        'plan-runner:merge-queue:*' 패턴만 사용하는지 검증.
        다른 패턴(merge-lock:*, merge-wait-queue:* 등)으로의 fallback 없음을 확인.
        """
        scan_patterns = []

        async def mock_get_merge_queue():
            # 실제 service 메서드 내부 scan_iter 호출 패턴을 캡처하기 위해
            # AsyncMock scan_iter를 주입하여 match 파라미터를 기록한다.
            import fakeredis.aioredis as _faio
            fake = _faio.FakeRedis(decode_responses=True)

            # scan_iter를 래핑하여 패턴 캡처
            original_scan_iter = fake.scan_iter

            async def capturing_scan_iter(match=None, **kwargs):
                if match:
                    scan_patterns.append(match)
                async for key in original_scan_iter(match=match, **kwargs):
                    yield key

            fake.scan_iter = capturing_scan_iter

            from app.modules.dev_runner.services.executor_service import ExecutorService
            svc = ExecutorService.__new__(ExecutorService)
            svc.async_redis = fake
            svc.redis_client = MagicMock()
            return await svc.get_merge_queue()

        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_merge_queue",
            new=mock_get_merge_queue
        ):
            resp = api_client.get(f"{BASE_URL}/merge-queue")

        assert resp.status_code == 200
        # scan_iter가 호출됐다면 plan-runner:merge-queue:* 패턴만 사용해야 함
        # (빈 DB에서 scan_iter가 호출되지 않을 수도 있으므로 호출된 경우만 검증)
        for pattern in scan_patterns:
            assert pattern == "plan-runner:merge-queue:*", (
                f"허용되지 않은 scan_iter 패턴 사용: {pattern}"
            )
