"""log_service Redis 재연결 시 connected 이벤트 재전송 TC

Redis ConnectionError 발생 후 pubsub 재생성 시 connected 이벤트를 재전송하는지 검증.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import redis.asyncio as aioredis

from app.modules.dev_runner.services.log_service import LogService


def _make_pubsub_mock(messages: list) -> MagicMock:
    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()
    mock_pubsub.get_message = AsyncMock(side_effect=messages + [None] * 200)
    return mock_pubsub


def _msg(data: str) -> dict:
    return {"type": "message", "data": data}


async def _collect(gen, max_items: int = 20, timeout: float = 2.0) -> list[str]:
    items = []
    for _ in range(max_items):
        try:
            chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
            items.append(chunk)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break
    return items


def _make_log_service_with_reconnect(
    first_pubsub_messages: list,
    second_pubsub_messages: list,
) -> LogService:
    """첫 번째 pubsub은 ConnectionError 발생, 두 번째는 정상 메시지 반환."""
    svc = LogService.__new__(LogService)

    pubsub1 = _make_pubsub_mock(first_pubsub_messages)
    pubsub2 = _make_pubsub_mock(second_pubsub_messages)

    mock_async_redis = MagicMock()
    mock_async_redis.ping = AsyncMock()
    mock_async_redis.pubsub = MagicMock(side_effect=[pubsub1, pubsub2])
    svc.async_redis = mock_async_redis
    return svc


def _make_log_service_no_error(messages: list) -> LogService:
    """ConnectionError 없이 정상 동작하는 LogService."""
    svc = LogService.__new__(LogService)
    mock_pubsub = _make_pubsub_mock(messages)
    mock_async_redis = MagicMock()
    mock_async_redis.ping = AsyncMock()
    mock_async_redis.pubsub = MagicMock(return_value=mock_pubsub)
    svc.async_redis = mock_async_redis
    return svc


class TestStreamLogFileReconnect:
    """stream_log_file: Redis 재연결 시 connected 이벤트 재전송"""

    @pytest.mark.asyncio
    async def test_stream_log_reconnect_sends_connected(self):
        """R: ConnectionError 발생 후 재연결 시 connected 이벤트 전송."""
        svc = _make_log_service_with_reconnect(
            first_pubsub_messages=[aioredis.ConnectionError("Redis down")],
            second_pubsub_messages=[_msg("__COMPLETED__")],
        )
        with patch("asyncio.sleep", new=AsyncMock()):
            events = await _collect(svc.stream_log_file("test-runner"))

        assert "event: connected\ndata: ok\n\n" in events
        assert "event: redis_disconnected\ndata: Redis not available\n\n" in events

        # connected가 redis_disconnected 이후에 와야 함
        idx_disconnected = events.index("event: redis_disconnected\ndata: Redis not available\n\n")
        # connected는 첫 번째(초기)와 재연결 후 두 번 있을 수 있음
        connected_indices = [i for i, e in enumerate(events) if e == "event: connected\ndata: ok\n\n"]
        assert any(i > idx_disconnected for i in connected_indices), \
            "redis_disconnected 이후 connected 이벤트가 없음"

    @pytest.mark.asyncio
    async def test_stream_log_reconnect_no_spurious_on_first(self):
        """B: ConnectionError 없는 정상 흐름에서 connected 이벤트가 정확히 1회."""
        svc = _make_log_service_no_error([_msg("__COMPLETED__")])
        events = await _collect(svc.stream_log_file("test-runner"))

        connected_count = events.count("event: connected\ndata: ok\n\n")
        assert connected_count == 1, f"초기 연결 시 connected 이벤트 1회여야 함, 실제: {connected_count}"

    @pytest.mark.asyncio
    async def test_stream_log_reconnect_multiple_disconnects(self):
        """B: 2회 연속 ConnectionError → 복구 시 connected 이벤트 포함."""
        svc = LogService.__new__(LogService)
        pubsub1 = _make_pubsub_mock([aioredis.ConnectionError("down")])
        pubsub2 = _make_pubsub_mock([aioredis.ConnectionError("still down")])
        pubsub3 = _make_pubsub_mock([_msg("__COMPLETED__")])

        mock_async_redis = MagicMock()
        mock_async_redis.ping = AsyncMock()
        mock_async_redis.pubsub = MagicMock(side_effect=[pubsub1, pubsub2, pubsub3])
        svc.async_redis = mock_async_redis

        with patch("asyncio.sleep", new=AsyncMock()):
            events = await _collect(svc.stream_log_file("test-runner"), max_items=30)

        disconnected_count = events.count("event: redis_disconnected\ndata: Redis not available\n\n")
        assert disconnected_count == 2, f"redis_disconnected 2회 기대, 실제: {disconnected_count}"

        # 마지막 disconnected 이후 connected가 있어야 함
        last_dc_idx = max(i for i, e in enumerate(events)
                          if e == "event: redis_disconnected\ndata: Redis not available\n\n")
        connected_after = [i for i, e in enumerate(events)
                           if e == "event: connected\ndata: ok\n\n" and i > last_dc_idx]
        assert connected_after, "마지막 redis_disconnected 이후 connected 이벤트 없음"


class TestStreamMergeLogReconnect:
    """stream_merge_log: Redis 재연결 시 connected 이벤트 재전송"""

    @pytest.mark.asyncio
    async def test_stream_merge_log_reconnect_sends_connected(self):
        """R: ConnectionError 발생 후 재연결 시 connected 이벤트 전송."""
        svc = _make_log_service_with_reconnect(
            first_pubsub_messages=[aioredis.ConnectionError("Redis down")],
            second_pubsub_messages=[_msg("__MERGE_COMPLETED__")],
        )
        with patch("asyncio.sleep", new=AsyncMock()):
            events = await _collect(svc.stream_merge_log("test-runner"))

        assert "event: redis_disconnected\ndata: Redis not available\n\n" in events
        idx_disconnected = events.index("event: redis_disconnected\ndata: Redis not available\n\n")
        connected_after = [i for i, e in enumerate(events)
                           if e == "event: connected\ndata: ok\n\n" and i > idx_disconnected]
        assert connected_after, "redis_disconnected 이후 connected 이벤트 없음"

    @pytest.mark.asyncio
    async def test_stream_merge_log_reconnect_no_spurious_on_first(self):
        """B: 정상 흐름에서 connected 이벤트 정확히 1회."""
        svc = _make_log_service_no_error([_msg("__MERGE_COMPLETED__")])
        events = await _collect(svc.stream_merge_log("test-runner"))

        connected_count = events.count("event: connected\ndata: ok\n\n")
        assert connected_count == 1, f"초기 연결 시 connected 이벤트 1회여야 함, 실제: {connected_count}"
