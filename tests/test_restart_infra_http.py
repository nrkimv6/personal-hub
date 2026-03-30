"""
restart_infra HTTP 통합 테스트 (T5)

TestClient로 infra restart API 엔드포인트 + worker_status tier 필드 검증
"""
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


class TestRestartInfraHttp:

    def _mock_redis(self, success: bool = True, message: str = "완료"):
        redis_mock = AsyncMock()
        redis_mock.delete = AsyncMock()
        redis_mock.lpush = AsyncMock()
        redis_mock.brpop = AsyncMock(return_value=(
            "infra:command_results",
            json.dumps({"success": success, "message": message})
        ))
        return redis_mock

    def test_http_restart_infra_success(self, client):
        """T5: POST /api/v1/system/services/infra/api_watchdog/restart → 200 + success 필드"""
        redis_mock = self._mock_redis(success=True)

        with patch("app.shared.redis.client.RedisClient") as mock_client:
            mock_client.get_client = AsyncMock(return_value=redis_mock)
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
