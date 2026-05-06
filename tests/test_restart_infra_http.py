"""
restart_infra HTTP 통합 테스트 (T5)

TestClient로 infra restart API 엔드포인트 + worker_status tier 필드 검증
"""
import subprocess
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _sp_ok(stdout="완료"):
    return MagicMock(returncode=0, stdout=stdout, stderr="")


class TestRestartInfraHttp:

    def test_http_restart_infra_success(self, client):
        """T5: POST /api/v1/system/services/infra/api_watchdog/restart → 200 + success 필드"""
        with patch("app.modules.system.services.worker_service.subprocess.run",
                   return_value=_sp_ok()) as mock_run:
            resp = client.post("/api/v1/system/services/infra/api_watchdog/restart")

        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert "message" in data

    def test_http_restart_infra_unknown_name(self, client):
        """T5: POST /api/v1/system/services/infra/unknown/restart → 200 + success: false + 에러 메시지"""
        resp = client.post("/api/v1/system/services/infra/unknown/restart")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "message" in data
        assert len(data["message"]) > 0

    def test_http_restart_infra_command_listener_success(self, client):
        """T5: POST /api/v1/system/services/infra/command_listener/restart → 200 + success/message 계약 유지"""
        with patch(
            "app.modules.system.services.worker_service.executor_service.restart_listener",
            return_value={"success": True, "message": "command listener restarted"},
        ) as mock_restart:
            resp = client.post("/api/v1/system/services/infra/command_listener/restart")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "message" in data
        mock_restart.assert_called_once()


class TestWorkerStatusTierHttp:

    def test_http_worker_status_includes_tier(self, client):
        """T5: GET /api/v1/system/services/workers → 응답 JSON 각 항목에 tier 필드 존재"""
        resp = client.get("/api/v1/system/services/workers")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

        for entry in data:
            assert "tier" in entry, f"tier 필드 없음: {entry.get('name')}"
            assert entry["tier"] in ("worker", "infra"), \
                f"tier 값이 예상 범위 밖: {entry['tier']} ({entry.get('name')})"
