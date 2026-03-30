"""
restart_infra E2E 테스트 (T4)

TestClient로 /api/v1/system/services/infra/{name}/restart 엔드포인트 검증
"""
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


class TestRestartInfraE2E:

    def _mock_redis(self, success: bool = True, message: str = "완료"):
        redis_mock = AsyncMock()
        redis_mock.delete = AsyncMock()
        redis_mock.lpush = AsyncMock()
        redis_mock.brpop = AsyncMock(return_value=(
            "infra:command_results",
            json.dumps({"success": success, "message": message})
        ))
        return redis_mock

    def test_e2e_restart_infra_valid_name(self, client):
        """T4: POST /api/v1/system/services/infra/api_watchdog/restart → 200 + success 필드"""
        redis_mock = self._mock_redis(success=True)

        with patch("app.shared.redis.client.RedisClient") as mock_client:
            mock_client.get_client = AsyncMock(return_value=redis_mock)
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
        """T4: POST /api/v1/system/services/infra/command_listener/restart → restart-listener 액션"""
        redis_mock = self._mock_redis(success=True)
        captured = {}

        async def fake_lpush(key, value):
            captured["key"] = key
            captured["payload"] = json.loads(value)

        redis_mock.lpush = fake_lpush

        with patch("app.shared.redis.client.RedisClient") as mock_client:
            mock_client.get_client = AsyncMock(return_value=redis_mock)
            resp = client.post("/api/v1/system/services/infra/command_listener/restart")

        assert resp.status_code == 200
        assert captured.get("key") == "infra:commands"
        assert captured.get("payload", {}).get("action") == "restart-listener"
