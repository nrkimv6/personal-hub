"""통합 테스트"""

import json
from datetime import datetime
from unittest.mock import patch

import pytest
import fakeredis
import fakeredis.aioredis

from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.services.state import get_state

RESULTS_KEY = "plan-runner:command_results"
STATE_KEY = "plan-runner:state"


@pytest.fixture(autouse=True)
def mock_executor_redis():
    """executor_service의 Redis를 fakeredis로 교체"""
    fake_sync = fakeredis.FakeRedis(decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(executor_service, 'redis_client', fake_sync), \
         patch.object(executor_service, 'async_redis', fake_async):
        yield {"async": fake_async, "sync": fake_sync}


class TestFullFlow:
    async def test_full_lifecycle(self, client, mock_executor_redis):
        fake_async = mock_executor_redis["async"]
        fake_sync = mock_executor_redis["sync"]
        now = datetime.now().isoformat()

        # 1. 초기 상태
        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        assert response.json()["running"] is False

        # 2. 시작 (listener heartbeat + 성공 응답 세팅)
        await fake_async.set("plan-runner:listener:heartbeat", now)
        await fake_async.rpush(RESULTS_KEY, json.dumps({"success": True, "message": "Started"}))
        await fake_async.set(f"{STATE_KEY}:pid", "55555")
        await fake_async.set(f"{STATE_KEY}:plan_file", "test.md")
        await fake_async.set(f"{STATE_KEY}:start_time", now)

        response = await client.post("/api/v1/dev-runner/run", json={"plan_file": "test.md"})
        assert response.status_code == 200
        assert response.json()["running"] is True

        # 3. 실행 중 확인 (status를 running으로 세팅)
        fake_sync.set(f"{STATE_KEY}:status", "running")
        fake_sync.set(f"{STATE_KEY}:pid", "55555")
        fake_sync.set(f"{STATE_KEY}:start_time", now)

        with patch.object(executor_service, '_is_pid_alive', return_value=True):
            response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        assert response.json()["running"] is True

        # 4. 중지
        await fake_async.set(f"{STATE_KEY}:status", "running")
        await fake_async.rpush(RESULTS_KEY, json.dumps({"success": True, "message": "Stopped"}))

        response = await client.post("/api/v1/dev-runner/stop")
        assert response.status_code == 200

        # 5. 중지 확인 (상태 정리 후)
        fake_sync.delete(f"{STATE_KEY}:status")
        fake_sync.delete(f"{STATE_KEY}:pid")

        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        assert response.json()["running"] is False


class TestPlansList:
    async def test_plans_list_returns_200(self, client):
        response = await client.get("/api/v1/dev-runner/plans")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestLogsRecent:
    async def test_logs_recent_returns_200(self, client):
        response = await client.get("/api/v1/dev-runner/logs/recent")
        assert response.status_code == 200
        data = response.json()
        assert "lines" in data
        assert "total_lines" in data
        assert isinstance(data["lines"], list)
