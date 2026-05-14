"""HTTP 통합 테스트 — cleanup-stale API (TestClient 기반)

Phase T5: POST /api/v1/dev-runner/runners/cleanup-stale 엔드포인트 검증
실제 Redis 없이 executor_service를 mock으로 교체하여 HTTP 레이어만 검증합니다.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

BASE_URL = "/api/v1/dev-runner"


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드 — plan_service 의존성 없음"""
    yield


@pytest.fixture
def client():
    """TestClient — DB/Redis 연결 없이 HTTP 레이어 테스트"""
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


def _mock_cleanup_stale(cleaned_active: int = 0, cleaned_recent: int = 0, bugs: int = 0):
    """cleanup_stale_runners()를 mock하는 패치 컨텍스트"""
    total = cleaned_active + cleaned_recent
    return patch(
        "app.modules.dev_runner.routes.runner.executor_service.cleanup_stale_runners",
        new_callable=AsyncMock,
        return_value={
            "cleaned_active": cleaned_active,
            "cleaned_recent": cleaned_recent,
            "bugs": bugs,
            "total": total,
        },
    )


class TestCleanupStaleEndpoint200:
    pytestmark = pytest.mark.http
    """POST /runners/cleanup-stale → 200 + success: true 검증"""

    def test_cleanup_stale_endpoint_returns_200(self, client):
        """정상 응답 200 + success: true + cleaned 필드 확인"""
        with _mock_cleanup_stale(cleaned_active=1, cleaned_recent=2):
            response = client.post(f"{BASE_URL}/runners/cleanup-stale")

        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data.get("cleaned") == 3
        assert "detail" in data
        assert data["detail"]["cleaned_active"] == 1
        assert data["detail"]["cleaned_recent"] == 2

    def test_cleanup_stale_endpoint_empty_returns_200(self, client):
        """정리 대상 없을 때도 200 + success: true + cleaned: 0"""
        with _mock_cleanup_stale(cleaned_active=0, cleaned_recent=0):
            response = client.post(f"{BASE_URL}/runners/cleanup-stale")

        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data.get("cleaned") == 0


class TestCleanupStaleEndpointIdempotent:
    pytestmark = pytest.mark.http
    """두 번 호출해도 동일한 응답 확인 (멱등성 검증)"""

    def test_cleanup_stale_endpoint_idempotent(self, client):
        """두 번 호출해도 동일한 응답 구조 반환"""
        with _mock_cleanup_stale(cleaned_active=0, cleaned_recent=1):
            response1 = client.post(f"{BASE_URL}/runners/cleanup-stale")

        with _mock_cleanup_stale(cleaned_active=0, cleaned_recent=0):
            response2 = client.post(f"{BASE_URL}/runners/cleanup-stale")

        assert response1.status_code == 200
        assert response2.status_code == 200

        data1 = response1.json()
        data2 = response2.json()

        # 두 응답 모두 동일한 스키마를 가져야 함
        assert data1.get("success") is True
        assert data2.get("success") is True
        assert "cleaned" in data1
        assert "cleaned" in data2
        assert "detail" in data1
        assert "detail" in data2

    def test_cleanup_stale_response_schema(self, client):
        """응답 JSON 스키마 검증 — 필수 필드 존재 확인"""
        with _mock_cleanup_stale(cleaned_active=2, cleaned_recent=1, bugs=1):
            response = client.post(f"{BASE_URL}/runners/cleanup-stale")

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data.get("success"), bool)
        assert isinstance(data.get("cleaned"), int)
        assert data["cleaned"] >= 0

        detail = data.get("detail", {})
        assert isinstance(detail.get("cleaned_active"), int)
        assert isinstance(detail.get("cleaned_recent"), int)


class TestDismissRunnerTabContract:
    pytestmark = pytest.mark.http
    """DELETE /runners/{runner_id}/tab 계약 검증"""

    def test_delete_tab_removes_runner_from_list(self, client):
        """dismiss 성공 후 GET /runners 목록에서 해당 runner가 제거된다."""
        before = [{"runner_id": "runner-dismiss-01", "running": False, "visible": True}]
        after = []

        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            side_effect=[before, after],
        ):
            with patch(
                "app.modules.dev_runner.routes.runner.executor_service.dismiss_runner",
                new_callable=AsyncMock,
                return_value=True,
            ) as dismiss_mock:
                before_resp = client.get(f"{BASE_URL}/runners")
                delete_resp = client.delete(f"{BASE_URL}/runners/runner-dismiss-01/tab")
                after_resp = client.get(f"{BASE_URL}/runners")

        assert before_resp.status_code == 200
        assert delete_resp.status_code == 200
        assert after_resp.status_code == 200
        assert [r["runner_id"] for r in before_resp.json()] == ["runner-dismiss-01"]
        assert after_resp.json() == []
        dismiss_mock.assert_awaited_once_with("runner-dismiss-01")

    def test_cleanup_stale_preserves_then_delete_tab_removes(self, client):
        """cleanup-stale 이후엔 탭 유지, DELETE /tab 이후에만 제거된다."""
        runner = [{"runner_id": "runner-preserve-01", "running": False, "visible": True}]

        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            side_effect=[runner, runner, []],
        ):
            with patch(
                "app.modules.dev_runner.routes.runner.executor_service.cleanup_stale_runners",
                new_callable=AsyncMock,
                return_value={
                    "cleaned_active": 0,
                    "cleaned_recent": 0,
                    "preserved_recent": 1,
                    "bugs": 0,
                    "total": 0,
                },
            ) as cleanup_mock, patch(
                "app.modules.dev_runner.routes.runner.executor_service.dismiss_runner",
                new_callable=AsyncMock,
                return_value=True,
            ) as dismiss_mock:
                before = client.get(f"{BASE_URL}/runners")
                cleanup = client.post(f"{BASE_URL}/runners/cleanup-stale")
                after_cleanup = client.get(f"{BASE_URL}/runners")
                delete = client.delete(f"{BASE_URL}/runners/runner-preserve-01/tab")
                after_delete = client.get(f"{BASE_URL}/runners")

        assert before.status_code == 200
        assert cleanup.status_code == 200
        assert after_cleanup.status_code == 200
        assert delete.status_code == 200
        assert after_delete.status_code == 200
        assert [r["runner_id"] for r in before.json()] == ["runner-preserve-01"]
        assert [r["runner_id"] for r in after_cleanup.json()] == ["runner-preserve-01"]
        assert cleanup.json().get("preserved_recent") == 1
        assert after_delete.json() == []
        cleanup_mock.assert_awaited_once()
        dismiss_mock.assert_awaited_once_with("runner-preserve-01")

    def test_cleanup_stale_and_dismiss_order_is_consistent(self, client):
        """dismiss 후 cleanup-stale를 호출해도 결과는 일관되게 빈 목록이다."""
        runner = [{"runner_id": "runner-order-01", "running": False, "visible": True}]

        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            side_effect=[runner, [], []],
        ):
            with patch(
                "app.modules.dev_runner.routes.runner.executor_service.dismiss_runner",
                new_callable=AsyncMock,
                return_value=True,
            ) as dismiss_mock, patch(
                "app.modules.dev_runner.routes.runner.executor_service.cleanup_stale_runners",
                new_callable=AsyncMock,
                return_value={
                    "cleaned_active": 0,
                    "cleaned_recent": 0,
                    "preserved_recent": 0,
                    "bugs": 0,
                    "total": 0,
                },
            ) as cleanup_mock:
                before = client.get(f"{BASE_URL}/runners")
                delete = client.delete(f"{BASE_URL}/runners/runner-order-01/tab")
                after_delete = client.get(f"{BASE_URL}/runners")
                cleanup = client.post(f"{BASE_URL}/runners/cleanup-stale")
                after_cleanup = client.get(f"{BASE_URL}/runners")

        assert before.status_code == 200
        assert delete.status_code == 200
        assert after_delete.status_code == 200
        assert cleanup.status_code == 200
        assert after_cleanup.status_code == 200
        assert [r["runner_id"] for r in before.json()] == ["runner-order-01"]
        assert after_delete.json() == []
        assert after_cleanup.json() == []
        dismiss_mock.assert_awaited_once_with("runner-order-01")
        cleanup_mock.assert_awaited_once()


# ──────────────────────────────────────────────
# T5: visible_only + stopped user 보존 계약 (Phase T5)
# ──────────────────────────────────────────────

class TestHttpLogHistoryVisibleOnly:
    pytestmark = pytest.mark.http
    """GET /logs/history?visible_only=true — stopped user 보존 계약 TC"""

    def test_logs_history_visible_only_returns_user_runner(self, client):
        """visible_only=True: trigger=user runner가 응답에 포함된다"""
        from unittest.mock import patch, MagicMock
        from app.modules.dev_runner.schemas import RunHistoryItem, RunHistoryResponse
        from datetime import datetime

        user_run = RunHistoryItem(
            runner_id="t5-user-01",
            plan_file="docs/plan/test.md",
            engine="claude",
            status="completed",
            pid=None,
            start_time=datetime(2026, 4, 6, 10, 0, 0),
            end_time=None,
            log_file=None,
            has_log=True,
            trigger="user",
        )
        mock_resp = RunHistoryResponse(runs=[user_run], total=1)

        with patch(
            "app.modules.dev_runner.routes.logs.log_service.get_run_history",
            return_value=mock_resp,
        ):
            response = client.get(f"{BASE_URL}/logs/history?visible_only=true")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["runs"][0]["runner_id"] == "t5-user-01"
        assert data["runs"][0]["trigger"] == "user"

    def test_logs_history_visible_only_excludes_tc_runner(self, client):
        """visible_only=True: trigger=tc:xxx runner는 응답에서 제외된다"""
        from unittest.mock import patch
        from app.modules.dev_runner.schemas import RunHistoryResponse

        mock_resp = RunHistoryResponse(runs=[], total=0)

        with patch(
            "app.modules.dev_runner.routes.logs.log_service.get_run_history",
            return_value=mock_resp,
        ):
            response = client.get(f"{BASE_URL}/logs/history?visible_only=true")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["runs"] == []

    def test_logs_history_default_visible_only(self, client):
        """visible_only 파라미터 없이 호출 시 → visible_only=True로 동작"""
        from unittest.mock import patch
        from app.modules.dev_runner.schemas import RunHistoryResponse

        mock_resp = RunHistoryResponse(runs=[], total=0)

        with patch(
            "app.modules.dev_runner.routes.logs.log_service.get_run_history",
            return_value=mock_resp,
        ) as mock_get:
            response = client.get(f"{BASE_URL}/logs/history")

        assert response.status_code == 200
        call_kwargs = mock_get.call_args[1] if mock_get.call_args else {}
        assert call_kwargs.get("visible_only") is True
