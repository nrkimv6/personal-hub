"""실행 제어 API 테스트 - Redis mock 적용"""

import json
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime

import pytest
import redis

from app.modules.auto_next.services.state import get_state


@pytest.fixture(autouse=True)
def mock_executor_redis():
    """executor_service의 async_redis와 redis_client를 mock"""
    with patch("app.modules.auto_next.services.executor_service.executor_service.async_redis") as mock_async, \
         patch("app.modules.auto_next.services.executor_service.executor_service.redis_client") as mock_sync:
        # 기본: not running
        mock_async.get = AsyncMock(return_value=None)
        mock_async.lpush = AsyncMock(return_value=1)
        mock_async.brpop = AsyncMock(return_value=None)
        mock_sync.get = MagicMock(return_value=None)
        mock_sync.delete = MagicMock()
        yield {"async": mock_async, "sync": mock_sync}


class TestGetStatus:
    async def test_get_status_not_running(self, client):
        response = await client.get("/api/v1/auto-next/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert data["pid"] is None

    async def test_get_status_running(self, client, mock_executor_redis):
        mock_sync = mock_executor_redis["sync"]
        mock_sync.get.side_effect = lambda key: {
            "auto-next:state:status": "running",
            "auto-next:state:pid": "12345",
            "auto-next:state:plan_file": "test.md",
            "auto-next:state:start_time": "2026-02-18T10:00:00",
        }.get(key)

        with patch("app.modules.auto_next.services.executor_service.executor_service._is_pid_alive", return_value=True):
            response = await client.get("/api/v1/auto-next/status")

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["pid"] == 12345


class TestStartRun:
    async def test_start_run_success(self, client, mock_executor_redis):
        mock_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()

        # brpop → 성공 응답
        mock_async.brpop = AsyncMock(return_value=(
            "auto-next:command_results",
            json.dumps({"success": True, "message": "Started"})
        ))
        # start 후 상태 조회
        call_count = 0
        async def mock_get(key):
            nonlocal call_count
            call_count += 1
            mapping = {
                "auto-next:state:status": None,  # 처음 확인: not running
                "auto-next:state:pid": "12345",
                "auto-next:state:plan_file": "test-plan.md",
                "auto-next:state:start_time": now,
            }
            # 첫 호출(status 확인)은 None, 이후는 매핑대로
            if call_count == 1:
                return None
            return mapping.get(key)

        mock_async.get = AsyncMock(side_effect=mock_get)

        response = await client.post("/api/v1/auto-next/run", json={
            "plan_file": "test-plan.md"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["pid"] == 12345

    async def test_double_start_returns_409(self, client, mock_executor_redis):
        mock_async = mock_executor_redis["async"]
        mock_async.get = AsyncMock(side_effect=lambda key: {
            "auto-next:state:status": "running",
            "auto-next:state:pid": "99999",
        }.get(key))

        response = await client.post("/api/v1/auto-next/run", json={
            "plan_file": "test-plan.md"
        })
        assert response.status_code == 409

    async def test_start_redis_down_503(self, client, mock_executor_redis):
        mock_async = mock_executor_redis["async"]
        mock_async.get = AsyncMock(side_effect=redis.ConnectionError("Connection refused"))

        response = await client.post("/api/v1/auto-next/run", json={
            "plan_file": "test.md"
        })
        assert response.status_code == 503

    async def test_start_brpop_timeout_504(self, client, mock_executor_redis):
        mock_async = mock_executor_redis["async"]
        # status check: not running → brpop: timeout (None)
        mock_async.get = AsyncMock(return_value=None)
        mock_async.brpop = AsyncMock(return_value=None)

        response = await client.post("/api/v1/auto-next/run", json={
            "plan_file": "test.md"
        })
        assert response.status_code == 504


class TestStopRun:
    async def test_stop_not_running_returns_404(self, client, mock_executor_redis):
        mock_async = mock_executor_redis["async"]
        mock_async.get = AsyncMock(return_value=None)

        response = await client.post("/api/v1/auto-next/stop")
        assert response.status_code == 404

    async def test_stop_running_process(self, client, mock_executor_redis):
        mock_async = mock_executor_redis["async"]
        mock_async.get = AsyncMock(return_value="running")
        mock_async.brpop = AsyncMock(return_value=(
            "auto-next:command_results",
            json.dumps({"success": True, "message": "Stopped"})
        ))

        response = await client.post("/api/v1/auto-next/stop")
        assert response.status_code == 200

    async def test_stop_redis_down_503(self, client, mock_executor_redis):
        mock_async = mock_executor_redis["async"]
        mock_async.get = AsyncMock(side_effect=redis.ConnectionError("Connection refused"))

        response = await client.post("/api/v1/auto-next/stop")
        assert response.status_code == 503
