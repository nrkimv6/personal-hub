"""통합 테스트"""

from unittest.mock import patch, MagicMock

import pytest

from app.modules.auto_next.services.state import get_state


class TestFullFlow:
    async def test_full_lifecycle(self, client, tmp_path):
        # 1. 초기 상태
        response = await client.get("/api/auto-next/status")
        assert response.status_code == 200
        assert response.json()["running"] is False

        # 2. 시작
        mock_process = MagicMock()
        mock_process.pid = 55555
        mock_process.poll.return_value = None
        mock_process.wait.return_value = 0

        with patch("app.modules.auto_next.services.executor_service.subprocess.Popen", return_value=mock_process):
            with patch("app.modules.auto_next.services.executor_service.config") as mock_config:
                mock_config.WTOOLS_BASE_DIR = tmp_path
                mock_config.LOG_DIR = "logs"
                mock_config.AUTO_NEXT_MODULE_PATH = tmp_path
                response = await client.post("/api/auto-next/run", json={"plan_file": "test.md"})
                assert response.status_code == 200
                assert response.json()["running"] is True

        # 3. 실행 중 확인
        response = await client.get("/api/auto-next/status")
        assert response.status_code == 200
        assert response.json()["running"] is True

        # 4. 중지
        response = await client.post("/api/auto-next/stop")
        assert response.status_code == 200

        # 5. 중지 확인
        response = await client.get("/api/auto-next/status")
        assert response.status_code == 200
        assert response.json()["running"] is False


class TestPlansList:
    async def test_plans_list_returns_200(self, client):
        response = await client.get("/api/auto-next/plans")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestLogsRecent:
    async def test_logs_recent_returns_200(self, client):
        response = await client.get("/api/auto-next/logs/recent")
        assert response.status_code == 200
        data = response.json()
        assert "lines" in data
        assert "total_lines" in data
        assert isinstance(data["lines"], list)
