"""
restart_infra E2E 테스트 (T4)

TestClient로 /api/v1/system/services/infra/{name}/restart 엔드포인트 검증
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


def _sp_fail(stderr="실패"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


class TestRestartInfraE2E:

    def test_e2e_restart_infra_valid_name(self, client):
        """T4: POST /api/v1/system/services/infra/api_watchdog/restart → 200 + success 필드"""
        with patch("app.modules.system.services.worker_service.subprocess.run",
                   return_value=_sp_ok()):
            resp = client.post("/api/v1/system/services/infra/api_watchdog/restart")

        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert data["success"] is True

    def test_e2e_restart_infra_invalid_name(self, client):
        """T4: POST /api/v1/system/services/infra/nonexistent/restart → 200 + success: false"""
        resp = client.post("/api/v1/system/services/infra/nonexistent/restart")

        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert data["success"] is False

    def test_e2e_restart_infra_command_listener(self, client):
        """T4: POST /api/v1/system/services/infra/command_listener/restart
        → executor_service.restart_listener() 경유, subprocess.run 미호출
        (Redis 시그널 방식 전환 후: SYSTEM 컨텍스트로 subprocess 직접 호출 금지)
        """
        with patch("app.modules.system.services.worker_service.subprocess.run") as mock_run, \
             patch(
                 "app.modules.system.services.worker_service.executor_service.restart_listener",
                 return_value={"success": True, "message": "listener restarted"},
             ) as mock_rl:
            resp = client.post("/api/v1/system/services/infra/command_listener/restart")

        assert resp.status_code == 200
        assert not mock_run.called, "subprocess.run이 호출됨 — SYSTEM 컨텍스트 오염 (Redis 시그널로 교체됨)"
        assert mock_rl.called, "executor_service.restart_listener가 호출되지 않음"
