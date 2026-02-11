"""실행 제어 API 테스트"""

from unittest.mock import patch, MagicMock
from datetime import datetime

import pytest

from app.modules.auto_next.services.state import get_state


class TestGetStatus:
    async def test_get_status_not_running(self, client):
        response = await client.get("/api/v1/auto-next/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert data["pid"] is None


class TestStartRun:
    async def test_start_run_success(self, client, tmp_path):
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None

        with patch("app.modules.auto_next.services.executor_service.subprocess.Popen", return_value=mock_process):
            with patch("app.modules.auto_next.services.executor_service.config") as mock_config:
                mock_config.WTOOLS_BASE_DIR = tmp_path
                mock_config.LOG_DIR = "logs"
                mock_config.AUTO_NEXT_MODULE_PATH = tmp_path

                response = await client.post("/api/v1/auto-next/run", json={
                    "plan_file": "test-plan.md"
                })

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["pid"] == 12345

    async def test_double_start_returns_409(self, client):
        state = get_state()
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        state.process = mock_process
        state.pid = 99999

        response = await client.post("/api/v1/auto-next/run", json={
            "plan_file": "test-plan.md"
        })
        assert response.status_code == 409


class TestStopRun:
    async def test_stop_not_running_returns_404(self, client):
        response = await client.post("/api/v1/auto-next/stop")
        assert response.status_code == 404

    async def test_stop_running_process(self, client):
        state = get_state()
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.wait.return_value = 0
        state.process = mock_process
        state.pid = 99999
        state.start_time = datetime.now()

        response = await client.post("/api/v1/auto-next/stop")
        assert response.status_code == 200
        mock_process.terminate.assert_called_once()
