"""
TC: _stream_sse_loop 단위 테스트 (Phase T1 #14)

LogService._stream_sse_loop의 핵심 동작 검증:
- R: completion 이벤트 수신 시 event: completed yield 후 종료
- R: heartbeat interval 경과 시 : heartbeat yield
- E: Redis ConnectionError 시 event: redis_disconnected yield 후 재연결 시도
- B: 연속 5회 예외 시 event: stream_error yield 후 스트림 종료
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis
import redis.asyncio as aioredis

from app.modules.dev_runner.services.log_service import LogService, HEARTBEAT_INTERVAL


def _make_log_service() -> LogService:
    """LogService 인스턴스 생성 (Redis 연결 없이)"""
    with patch("app.modules.dev_runner.services.log_service.RedisClient") as mock_rc:
        mock_rc.get_sync_client.return_value = MagicMock()
        with patch("app.modules.dev_runner.services.log_service.aioredis.ConnectionPool"):
            with patch("app.modules.dev_runner.services.log_service.aioredis.Redis"):
                svc = LogService()
    return svc


def _make_pubsub_mock(messages: list):
    """메시지 시퀀스를 반환하는 pubsub mock 생성.

    messages: list of (type, data) tuples or None (no message)
    """
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.punsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()

    msg_queue = list(messages)

    async def get_message(ignore_subscribe_messages=True, timeout=0.5):
        if not msg_queue:
            return None
        item = msg_queue.pop(0)
        if item is None:
            return None
        msg_type, msg_data = item
        return {"type": msg_type, "data": msg_data}

    pubsub.get_message = get_message
    return pubsub


class TestStreamSSELoop:
    """_stream_sse_loop 동작 검증"""

    @pytest.mark.asyncio
    async def test_stream_sse_loop_completion_event(self):
        """R: completion 이벤트 수신 시 event: completed yield 후 정상 종료"""
        svc = _make_log_service()

        def completion_checker(data):
            return data == "DONE:success"

        def completion_parser(data):
            return data, "success"

        pubsub_mock = _make_pubsub_mock([
            ("message", "log line 1"),
            ("message", "DONE:success"),
        ])

        async_redis_mock = MagicMock()
        async_redis_mock.pubsub.return_value = pubsub_mock  # pubsub()은 sync 호출

        svc.async_redis = async_redis_mock

        collected = []
        async for event in svc._stream_sse_loop("test:channel", completion_checker, completion_parser, multiline_frame=False):
            collected.append(event)
            if len(collected) > 10:  # 무한루프 방어
                break

        assert any("event: completed" in e for e in collected), f"collected: {collected}"
        assert any("data: success" in e for e in collected), f"collected: {collected}"

    @pytest.mark.asyncio
    async def test_stream_sse_loop_heartbeat_interval(self):
        """R: 메시지 없을 때 HEARTBEAT_INTERVAL 경과 후 : heartbeat yield"""
        svc = _make_log_service()

        call_count = [0]
        MAX_CALLS = 3

        async def get_message_no_msg(ignore_subscribe_messages=True, timeout=0.5):
            call_count[0] += 1
            if call_count[0] > MAX_CALLS:
                raise StopAsyncIteration("test stop")
            return None

        pubsub_mock = AsyncMock()
        pubsub_mock.subscribe = AsyncMock()
        pubsub_mock.unsubscribe = AsyncMock()
        pubsub_mock.punsubscribe = AsyncMock()
        pubsub_mock.aclose = AsyncMock()
        pubsub_mock.get_message = get_message_no_msg

        async_redis_mock = MagicMock()
        async_redis_mock.pubsub.return_value = pubsub_mock  # pubsub()은 sync 호출

        svc.async_redis = async_redis_mock

        # last_heartbeat를 과거로 설정하여 즉시 heartbeat 트리거
        collected = []
        original_monotonic = time.monotonic
        base_time = original_monotonic()

        call_idx = [0]

        def mock_monotonic():
            call_idx[0] += 1
            # 처음 호출은 실제 시간, 이후는 HEARTBEAT_INTERVAL+1초 경과한 것처럼
            if call_idx[0] <= 2:
                return base_time
            return base_time + HEARTBEAT_INTERVAL + 1

        with patch("app.modules.dev_runner.services.log_service.time.monotonic", mock_monotonic):
            with patch("app.modules.dev_runner.services.log_service.asyncio.sleep", AsyncMock()):
                try:
                    async for event in svc._stream_sse_loop(
                        "test:channel",
                        lambda d: False,
                        lambda d: (d, d),
                        multiline_frame=False,
                    ):
                        collected.append(event)
                        if len(collected) >= 1:
                            break
                except StopAsyncIteration:
                    pass

        assert any(": heartbeat" in e for e in collected), f"heartbeat not found: {collected}"

    @pytest.mark.asyncio
    async def test_stream_sse_loop_heartbeat_boundary_single_emit(self):
        """B: interval 경과 시 heartbeat는 1회만 방출된다."""
        svc = _make_log_service()

        call_count = [0]
        max_calls = 4

        async def get_message_no_msg(ignore_subscribe_messages=True, timeout=0.5):
            call_count[0] += 1
            if call_count[0] > max_calls:
                raise StopAsyncIteration("test stop")
            return None

        pubsub_mock = AsyncMock()
        pubsub_mock.subscribe = AsyncMock()
        pubsub_mock.unsubscribe = AsyncMock()
        pubsub_mock.punsubscribe = AsyncMock()
        pubsub_mock.aclose = AsyncMock()
        pubsub_mock.get_message = get_message_no_msg

        async_redis_mock = MagicMock()
        async_redis_mock.pubsub.return_value = pubsub_mock
        svc.async_redis = async_redis_mock

        base_time = time.monotonic()
        call_idx = [0]

        def mock_monotonic():
            call_idx[0] += 1
            if call_idx[0] <= 2:
                return base_time
            return base_time + HEARTBEAT_INTERVAL + 1

        collected = []
        with patch("app.modules.dev_runner.services.log_service.time.monotonic", mock_monotonic):
            with patch("app.modules.dev_runner.services.log_service.asyncio.sleep", AsyncMock()):
                try:
                    async for event in svc._stream_sse_loop(
                        "test:channel",
                        lambda d: False,
                        lambda d: (d, d),
                        multiline_frame=False,
                    ):
                        collected.append(event)
                        if len(collected) >= 2:
                            break
                except StopAsyncIteration:
                    pass

        heartbeat_events = [e for e in collected if ": heartbeat" in e]
        assert len(heartbeat_events) == 1, f"heartbeat events: {collected}"

    @pytest.mark.asyncio
    async def test_stream_sse_loop_no_heartbeat_before_interval(self):
        """B: interval 경과 전에는 heartbeat를 방출하지 않는다."""
        svc = _make_log_service()

        call_count = [0]
        max_calls = 3

        async def get_message_no_msg(ignore_subscribe_messages=True, timeout=0.5):
            call_count[0] += 1
            if call_count[0] > max_calls:
                raise StopAsyncIteration("test stop")
            return None

        pubsub_mock = AsyncMock()
        pubsub_mock.subscribe = AsyncMock()
        pubsub_mock.unsubscribe = AsyncMock()
        pubsub_mock.punsubscribe = AsyncMock()
        pubsub_mock.aclose = AsyncMock()
        pubsub_mock.get_message = get_message_no_msg

        async_redis_mock = MagicMock()
        async_redis_mock.pubsub.return_value = pubsub_mock
        svc.async_redis = async_redis_mock

        base_time = time.monotonic()
        call_idx = [0]

        def mock_monotonic():
            call_idx[0] += 1
            return base_time

        collected = []
        with patch("app.modules.dev_runner.services.log_service.time.monotonic", mock_monotonic):
            with patch("app.modules.dev_runner.services.log_service.asyncio.sleep", AsyncMock()):
                try:
                    async for event in svc._stream_sse_loop(
                        "test:channel",
                        lambda d: False,
                        lambda d: (d, d),
                        multiline_frame=False,
                    ):
                        collected.append(event)
                except StopAsyncIteration:
                    pass

        assert not any(": heartbeat" in e for e in collected), f"heartbeat should not appear: {collected}"

    @pytest.mark.asyncio
    async def test_stream_sse_loop_redis_reconnect(self):
        """E: Redis ConnectionError 발생 시 event: redis_disconnected yield"""
        svc = _make_log_service()

        call_count = [0]

        async def get_message_error(ignore_subscribe_messages=True, timeout=0.5):
            call_count[0] += 1
            if call_count[0] == 1:
                raise redis.ConnectionError("Redis down")
            # 2번째 호출은 stop (무한루프 방어)
            raise StopAsyncIteration("test stop")

        pubsub_mock = AsyncMock()
        pubsub_mock.subscribe = AsyncMock()
        pubsub_mock.unsubscribe = AsyncMock()
        pubsub_mock.punsubscribe = AsyncMock()
        pubsub_mock.aclose = AsyncMock()
        pubsub_mock.get_message = get_message_error

        async_redis_mock = MagicMock()
        async_redis_mock.pubsub.return_value = pubsub_mock  # pubsub()은 sync 호출

        svc.async_redis = async_redis_mock

        collected = []
        with patch("app.modules.dev_runner.services.log_service.asyncio.sleep", AsyncMock()):
            try:
                async for event in svc._stream_sse_loop(
                    "test:channel",
                    lambda d: False,
                    lambda d: (d, d),
                    multiline_frame=False,
                ):
                    collected.append(event)
                    if len(collected) >= 1:
                        break
            except StopAsyncIteration:
                pass

        assert any("event: redis_disconnected" in e for e in collected), f"collected: {collected}"

    @pytest.mark.asyncio
    async def test_stream_sse_loop_max_consecutive_errors(self):
        """B: 연속 5회 예외 시 event: stream_error yield 후 스트림 종료"""
        svc = _make_log_service()

        call_count = [0]

        async def get_message_error(ignore_subscribe_messages=True, timeout=0.5):
            call_count[0] += 1
            raise ValueError(f"error #{call_count[0]}")

        pubsub_mock = AsyncMock()
        pubsub_mock.subscribe = AsyncMock()
        pubsub_mock.unsubscribe = AsyncMock()
        pubsub_mock.punsubscribe = AsyncMock()
        pubsub_mock.aclose = AsyncMock()
        pubsub_mock.get_message = get_message_error

        async_redis_mock = MagicMock()
        async_redis_mock.pubsub.return_value = pubsub_mock  # pubsub()은 sync 호출

        svc.async_redis = async_redis_mock

        collected = []
        with patch("app.modules.dev_runner.services.log_service.asyncio.sleep", AsyncMock()):
            async for event in svc._stream_sse_loop(
                "test:channel",
                lambda d: False,
                lambda d: (d, d),
                multiline_frame=False,
            ):
                collected.append(event)

        # stream_error 이벤트가 있어야 하고, 이후 스트림이 종료되어야 함
        assert any("event: stream_error" in e for e in collected), f"collected: {collected}"
        # 마지막 이벤트가 stream_error
        assert "event: stream_error" in collected[-1], f"last event: {collected[-1]}"
