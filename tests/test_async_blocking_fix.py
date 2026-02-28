"""async 핸들러 내 동기 블로킹 호출 수정 테스트

executor_service.py의 메서드들이 async로 전환되어
이벤트 루프를 블로킹하지 않는지 검증한다.
"""
import asyncio
import inspect
import json
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import redis

from app.modules.dev_runner.services.executor_service import ExecutorService, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RESULTS_KEY


@pytest.fixture
def service():
    """async_redis를 AsyncMock으로 패치한 ExecutorService 인스턴스"""
    svc = ExecutorService.__new__(ExecutorService)
    svc.redis_client = MagicMock()
    svc.async_redis = AsyncMock()
    return svc


# --- Phase T1: TC ---

@pytest.mark.asyncio
async def test_send_force_stop_async(service):
    """R: _send_force_stop이 async_redis를 사용하여 정상 동작"""
    service.async_redis.brpop.return_value = ("key", json.dumps({"message": "stopped"}))

    result = await service._send_force_stop("test-runner")

    assert result is True
    service.async_redis.lpush.assert_called_once()
    service.async_redis.brpop.assert_called_once()
    service.async_redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_send_force_stop_timeout(service, caplog):
    """B: brpop 타임아웃 시 False 반환 + 경고 로그"""
    service.async_redis.brpop.return_value = None

    with caplog.at_level(logging.WARNING):
        result = await service._send_force_stop("test-runner")

    assert result is False
    assert "force-stop" in caplog.text


@pytest.mark.asyncio
async def test_reset_running_state_async(service):
    """R: reset_running_state가 async로 정상 동작"""
    service.async_redis.brpop.return_value = ("key", json.dumps({"message": "ok"}))
    service.redis_client.smembers.return_value = set()

    result = await service.reset_running_state()

    assert result["success"] is True
    # _send_force_stop이 async_redis를 사용했는지 확인
    service.async_redis.lpush.assert_called_once()


@pytest.mark.asyncio
async def test_get_all_runners_async(service):
    """R: get_all_runners가 async_redis로 runner 목록 반환"""
    service.async_redis.zremrangebyscore.return_value = 0
    service.async_redis.smembers.return_value = {"runner1"}
    service.async_redis.zrange.return_value = []
    # per-runner 키 mock
    async def mock_get(key):
        mapping = {
            f"{RUNNER_KEY_PREFIX}:runner1:status": "running",
            f"{RUNNER_KEY_PREFIX}:runner1:pid": "1234",
            f"{RUNNER_KEY_PREFIX}:runner1:plan_file": "test.md",
            f"{RUNNER_KEY_PREFIX}:runner1:engine": "claude",
            f"{RUNNER_KEY_PREFIX}:runner1:start_time": None,
            f"{RUNNER_KEY_PREFIX}:runner1:worktree_path": None,
            f"{RUNNER_KEY_PREFIX}:runner1:merge_status": None,
        }
        return mapping.get(key)
    service.async_redis.get = mock_get

    result = await service.get_all_runners()

    assert len(result) == 1
    assert result[0].runner_id == "runner1"
    assert result[0].running is True


@pytest.mark.asyncio
async def test_get_all_runners_empty(service):
    """B: runner가 없을 때 빈 리스트 반환"""
    service.async_redis.zremrangebyscore.return_value = 0
    service.async_redis.smembers.return_value = set()
    service.async_redis.zrange.return_value = []

    result = await service.get_all_runners()

    assert result == []


@pytest.mark.asyncio
async def test_get_all_runners_redis_down(service):
    """E: Redis 장애 시 빈 리스트 반환"""
    service.async_redis.zremrangebyscore.side_effect = redis.ConnectionError("Connection refused")

    result = await service.get_all_runners()

    assert result == []


@pytest.mark.asyncio
async def test_get_process_status_async(service):
    """R: get_process_status가 async_redis 사용"""
    service.async_redis.ping.return_value = True
    service.async_redis.get.return_value = None
    service.async_redis.smembers.return_value = set()

    result = await service.get_process_status()

    assert result.running is False
    assert result.redis_connected is True
    service.async_redis.ping.assert_called_once()


@pytest.mark.asyncio
async def test_get_process_status_redis_down(service):
    """E: Redis 장애 시 redis_connected=False 반환"""
    service.async_redis.ping.side_effect = redis.ConnectionError("Connection refused")

    result = await service.get_process_status()

    assert result.running is False
    assert result.redis_connected is False


@pytest.mark.asyncio
async def test_dismiss_runner_async(service):
    """R: dismiss_runner가 async_redis 사용"""
    service.async_redis.zrem.return_value = 1
    service.async_redis.delete.return_value = 1
    service.async_redis.srem.return_value = 0

    result = await service.dismiss_runner("test-runner")

    assert result is True
    service.async_redis.zrem.assert_called_once()
    service.async_redis.srem.assert_called_once()


def test_restart_listener_uses_to_thread():
    """R: restart_listener 라우터가 async def + asyncio.to_thread 사용"""
    from app.modules.dev_runner.routes import runner as runner_module
    handler = runner_module.restart_listener
    # async 함수인지 확인
    assert inspect.iscoroutinefunction(handler), "restart_listener must be async def"
    # 소스 코드에 asyncio.to_thread 포함 확인
    source = inspect.getsource(handler)
    assert "asyncio.to_thread" in source, "restart_listener must use asyncio.to_thread"


def test_redis_socket_timeout_set():
    """Co: 동기 Redis 클라이언트에 socket_timeout=10 설정 확인"""
    with patch("redis.Redis") as mock_redis_cls:
        mock_redis_cls.return_value = MagicMock()
        svc = ExecutorService()
        call_kwargs = mock_redis_cls.call_args[1]
        assert call_kwargs.get("socket_timeout") == 10, f"socket_timeout should be 10, got {call_kwargs.get('socket_timeout')}"
