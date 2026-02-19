"""실행 제어 API 테스트 - fakeredis + patch.object 적용"""

import json
from unittest.mock import patch, AsyncMock
from datetime import datetime

import pytest
import redis
import fakeredis
import fakeredis.aioredis

from app.modules.auto_next.services.executor_service import executor_service
from app.modules.auto_next.services.state import get_state

RESULTS_KEY = "auto-next:command_results"


@pytest.fixture(autouse=True)
def mock_executor_redis():
    """executor_service의 async_redis와 redis_client를 fakeredis로 교체"""
    fake_sync = fakeredis.FakeRedis(decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(executor_service, 'redis_client', fake_sync), \
         patch.object(executor_service, 'async_redis', fake_async):
        yield {"async": fake_async, "sync": fake_sync}


class TestGetStatus:
    async def test_get_status_not_running(self, client):
        response = await client.get("/api/v1/auto-next/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert data["pid"] is None

    async def test_get_status_running(self, client, mock_executor_redis):
        fake_sync = mock_executor_redis["sync"]
        fake_sync.set("auto-next:state:status", "running")
        fake_sync.set("auto-next:state:pid", "12345")
        fake_sync.set("auto-next:state:plan_file", "test.md")
        fake_sync.set("auto-next:state:start_time", "2026-02-18T10:00:00")
        fake_sync.set("auto-next:listener:heartbeat", "2026-02-18T10:00:00")

        response = await client.get("/api/v1/auto-next/status")

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["pid"] == 12345
        assert data["listener_alive"] is True


class TestGetStatusListenerAlive:
    """listener_alive 필드 테스트"""

    async def test_listener_alive_true_when_heartbeat_exists(self, client, mock_executor_redis):
        fake_sync = mock_executor_redis["sync"]
        fake_sync.set("auto-next:listener:heartbeat", "2026-02-19T10:00:00")
        # running=False이지만 listener는 살아있음

        response = await client.get("/api/v1/auto-next/status")
        assert response.status_code == 200
        data = response.json()
        assert data["listener_alive"] is True
        assert data["running"] is False

    async def test_listener_alive_false_when_no_heartbeat(self, client, mock_executor_redis):
        # heartbeat 없음

        response = await client.get("/api/v1/auto-next/status")
        assert response.status_code == 200
        data = response.json()
        assert data["listener_alive"] is False
        assert data["running"] is False

    async def test_running_true_with_heartbeat(self, client, mock_executor_redis):
        fake_sync = mock_executor_redis["sync"]
        fake_sync.set("auto-next:listener:heartbeat", "2026-02-19T10:00:00")
        fake_sync.set("auto-next:state:status", "running")
        fake_sync.set("auto-next:state:pid", "12345")
        fake_sync.set("auto-next:state:start_time", "2026-02-19T10:00:00")

        response = await client.get("/api/v1/auto-next/status")
        assert response.status_code == 200
        data = response.json()
        assert data["listener_alive"] is True
        assert data["running"] is True
        assert data["pid"] == 12345

    async def test_stale_running_without_heartbeat(self, client, mock_executor_redis):
        """running=True이지만 heartbeat 없음 → stale 정리 → running=False"""
        fake_sync = mock_executor_redis["sync"]
        fake_sync.set("auto-next:state:status", "running")
        fake_sync.set("auto-next:state:pid", "12345")
        # heartbeat 없음

        response = await client.get("/api/v1/auto-next/status")
        assert response.status_code == 200
        data = response.json()
        assert data["listener_alive"] is False
        assert data["running"] is False


class TestStartRun:
    async def test_start_run_success(self, client, mock_executor_redis):
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()

        # listener heartbeat 세팅 (사전 확인 통과용)
        await fake_async.set("auto-next:listener:heartbeat", now)
        # brpop 결과 미리 세팅 (listener 성공 응답)
        await fake_async.rpush(RESULTS_KEY, json.dumps({"success": True, "message": "Started"}))
        # start 후 상태 조회를 위한 상태 키 세팅
        await fake_async.set("auto-next:state:pid", "12345")
        await fake_async.set("auto-next:state:plan_file", "test-plan.md")
        await fake_async.set("auto-next:state:start_time", now)

        response = await client.post("/api/v1/auto-next/run", json={
            "plan_file": "test-plan.md"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["pid"] == 12345

    async def test_double_start_returns_409(self, client, mock_executor_redis):
        fake_async = mock_executor_redis["async"]
        # listener heartbeat 세팅
        await fake_async.set("auto-next:listener:heartbeat", datetime.now().isoformat())
        await fake_async.set("auto-next:state:status", "running")
        await fake_async.set("auto-next:state:pid", "99999")

        response = await client.post("/api/v1/auto-next/run", json={
            "plan_file": "test-plan.md"
        })
        assert response.status_code == 409

    async def test_start_redis_down_503(self, client, mock_executor_redis):
        # ConnectionError 테스트: ping에서 실패하도록 mock
        with patch.object(executor_service, 'async_redis') as mock_async:
            mock_async.ping = AsyncMock(side_effect=redis.ConnectionError("Connection refused"))
            response = await client.post("/api/v1/auto-next/run", json={
                "plan_file": "test.md"
            })
        assert response.status_code == 503

    async def test_start_listener_not_running_503(self, client, mock_executor_redis):
        """listener heartbeat 없으면 503"""
        # heartbeat 키를 세팅하지 않음 → listener 미실행 판정
        response = await client.post("/api/v1/auto-next/run", json={
            "plan_file": "test.md"
        })
        assert response.status_code == 503

    async def test_start_brpop_timeout_504(self, client, mock_executor_redis):
        fake_async = mock_executor_redis["async"]
        # listener heartbeat 세팅 (사전 확인 통과)
        await fake_async.set("auto-next:listener:heartbeat", datetime.now().isoformat())
        # status: not running (None), brpop: timeout → None 반환
        # fakeredis는 데이터 없을 때 brpop이 즉시 None 반환
        response = await client.post("/api/v1/auto-next/run", json={
            "plan_file": "test.md"
        })
        assert response.status_code == 504


class TestStopRun:
    async def test_stop_not_running_returns_404(self, client, mock_executor_redis):
        # fakeredis 빈 상태 → status None → not running → 404
        response = await client.post("/api/v1/auto-next/stop")
        assert response.status_code == 404

    async def test_stop_running_process(self, client, mock_executor_redis):
        fake_async = mock_executor_redis["async"]
        await fake_async.set("auto-next:state:status", "running")
        await fake_async.rpush(RESULTS_KEY, json.dumps({"success": True, "message": "Stopped"}))

        response = await client.post("/api/v1/auto-next/stop")
        assert response.status_code == 200

    async def test_stop_redis_down_503(self, client, mock_executor_redis):
        # ConnectionError 테스트: ping에서 실패하도록 mock
        with patch.object(executor_service, 'async_redis') as mock_async:
            mock_async.ping = AsyncMock(side_effect=redis.ConnectionError("Connection refused"))
            response = await client.post("/api/v1/auto-next/stop")
        assert response.status_code == 503
