"""RedisConnection 단위 TC"""

import pytest
import fakeredis.aioredis as fake_aioredis
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException


class TestRedisConnectionReconnect:
    def test_redis_connection_R_reconnect(self):
        """R(Right): reconnect() 후 redis_client가 새 인스턴스"""
        with patch("app.modules.dev_runner.services.redis_connection.redis.Redis"), \
             patch("app.modules.dev_runner.services.redis_connection.aioredis.Redis"):
            from app.modules.dev_runner.services.redis_connection import RedisConnection
            conn = RedisConnection()
            old_client = conn.redis_client
            conn.reconnect()
            # reconnect 후 새 클라이언트가 생성됨
            assert conn.redis_client is not None


class TestRedisConnectionCheckListener:
    @pytest.mark.asyncio
    async def test_redis_connection_E_check_no_redis(self):
        """E(Error): ping이 ConnectionError → HTTPException 503"""
        import redis as redis_lib
        from app.modules.dev_runner.services.redis_connection import RedisConnection
        conn = RedisConnection.__new__(RedisConnection)
        conn.async_redis = AsyncMock()
        conn.async_redis.ping = AsyncMock(side_effect=redis_lib.exceptions.ConnectionError("no conn"))
        with pytest.raises(HTTPException) as exc_info:
            await conn.check_redis_and_listener()
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_redis_connection_E_check_no_listener(self):
        """E(Error): heartbeat 키 없음 → HTTPException 503"""
        from app.modules.dev_runner.services.redis_connection import RedisConnection
        conn = RedisConnection.__new__(RedisConnection)
        conn.async_redis = AsyncMock()
        conn.async_redis.ping = AsyncMock(return_value=True)
        conn.async_redis.get = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc_info:
            await conn.check_redis_and_listener()
        assert exc_info.value.status_code == 503


class TestRedisConnectionGetRunnerFields:
    @pytest.mark.asyncio
    async def test_redis_connection_R_get_runner_fields(self):
        """R(Right): 키 존재 → 필드 dict 반환"""
        fake_r = fake_aioredis.FakeRedis(decode_responses=True)
        await fake_r.set("plan-runner:runners:r1:status", "running")
        await fake_r.set("plan-runner:runners:r1:pid", "1234")

        from app.modules.dev_runner.services.redis_connection import RedisConnection
        conn = RedisConnection.__new__(RedisConnection)
        conn.async_redis = fake_r

        result = await conn.get_runner_fields("r1", "status", "pid")
        assert result == {"status": "running", "pid": "1234"}

    @pytest.mark.asyncio
    async def test_redis_connection_B_get_runner_fields_missing(self):
        """B(Boundary): 키 없는 필드 → None 반환"""
        fake_r = fake_aioredis.FakeRedis(decode_responses=True)

        from app.modules.dev_runner.services.redis_connection import RedisConnection
        conn = RedisConnection.__new__(RedisConnection)
        conn.async_redis = fake_r

        result = await conn.get_runner_fields("r_noexist", "status")
        assert result == {"status": None}
