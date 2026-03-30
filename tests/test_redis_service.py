"""
RedisService 단위 테스트
"""
import pytest
from unittest.mock import patch, MagicMock


def test_redis_service_import():
    """R(Right): RedisService import 성공"""
    from app.modules.system.services.redis_service import RedisService
    assert RedisService is not None


@pytest.mark.asyncio
async def test_get_redis_status_no_connection():
    """E(Error): Redis 미연결 → connected=False"""
    from app.modules.system.services.redis_service import RedisService

    def _failing_redis():
        import redis as redis_lib
        raise redis_lib.ConnectionError("Connection refused")

    svc = RedisService()
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = MagicMock(
            side_effect=Exception("connection refused")
        )
        result = await svc.get_redis_status()

    assert result["connected"] is False


@pytest.mark.asyncio
async def test_get_redis_status_shape():
    """R(Right): 반환 dict에 필수 키 존재"""
    from app.modules.system.services.redis_service import RedisService
    svc = RedisService()

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = MagicMock(
            side_effect=Exception("connection refused")
        )
        result = await svc.get_redis_status()

    assert "connected" in result
    assert "container_running" in result
    assert "uptime_seconds" in result
    assert "used_memory_mb" in result
    assert "connected_clients" in result
