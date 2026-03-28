"""ExecutorService._send_command 단위 TC"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from app.modules.dev_runner.services.executor_service import ExecutorService


def make_svc():
    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = AsyncMock()
    return svc


class TestSendCommand:
    @pytest.mark.asyncio
    async def test_executor_R_send_command(self):
        """R(Right): brpop 정상 → lpush 1회, delete 호출, 반환값 dict"""
        svc = make_svc()
        svc.async_redis.brpop = AsyncMock(
            return_value=("key", json.dumps({"success": True}).encode())
        )
        svc.async_redis.lpush = AsyncMock(return_value=1)
        svc.async_redis.delete = AsyncMock()

        result = await svc._send_command({"action": "test"})

        assert result == {"success": True}
        svc.async_redis.lpush.assert_called_once()
        svc.async_redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_executor_E_send_command_timeout(self):
        """E(Error): brpop → None (timeout) → None 반환 + delete 호출"""
        svc = make_svc()
        svc.async_redis.brpop = AsyncMock(return_value=None)
        svc.async_redis.lpush = AsyncMock(return_value=1)
        svc.async_redis.delete = AsyncMock()

        result = await svc._send_command({"action": "test"})

        assert result is None
        svc.async_redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_executor_B_send_command_auto_command_id(self):
        """B(Boundary): command에 command_id 없음 → lpush에 command_id 자동 부여"""
        svc = make_svc()
        captured = []

        async def capture_lpush(key, val):
            captured.append(json.loads(val))
            return 1
        svc.async_redis.lpush = AsyncMock(side_effect=capture_lpush)
        svc.async_redis.brpop = AsyncMock(
            return_value=("key", json.dumps({"success": True}).encode())
        )
        svc.async_redis.delete = AsyncMock()

        await svc._send_command({"action": "no_id"})

        assert len(captured) == 1
        assert "command_id" in captured[0]
        assert len(captured[0]["command_id"]) == 8

    @pytest.mark.asyncio
    async def test_executor_B_send_command_preserves_command_id(self):
        """B(Boundary): command에 command_id 있으면 그대로 유지"""
        svc = make_svc()
        captured = []

        async def capture_lpush(key, val):
            captured.append(json.loads(val))
            return 1
        svc.async_redis.lpush = AsyncMock(side_effect=capture_lpush)
        svc.async_redis.brpop = AsyncMock(
            return_value=("key", json.dumps({"success": True}).encode())
        )
        svc.async_redis.delete = AsyncMock()

        await svc._send_command({"action": "with_id", "command_id": "mycustomid"})

        assert captured[0]["command_id"] == "mycustomid"
