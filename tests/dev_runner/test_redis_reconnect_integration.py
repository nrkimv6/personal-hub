"""Redis 재연결 시나리오 통합 TC

mock 최소화 — asyncio.sleep만 패치하고, LogService 인스턴스 직접 사용.
pubsub 두 개를 순서대로 반환하여 첫 번째에서 ConnectionError 발생 + 두 번째에서 정상 복구.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
import redis.asyncio as aioredis

from app.modules.dev_runner.services.log_service import LogService


def _msg(data: str) -> dict:
    return {"type": "message", "data": data}


async def _collect(gen, max_items: int = 30, timeout: float = 2.0) -> list[str]:
    items = []
    for _ in range(max_items):
        try:
            chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
            items.append(chunk)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break
    return items


def _build_service(first_pubsub_side_effect: list, second_pubsub_messages: list) -> LogService:
    """
    첫 번째 pubsub.get_message → ConnectionError 발생
    두 번째 pubsub.get_message → 정상 메시지 반환
    """
    svc = LogService.__new__(LogService)

    pubsub1 = AsyncMock()
    pubsub1.subscribe = AsyncMock()
    pubsub1.unsubscribe = AsyncMock()
    pubsub1.aclose = AsyncMock()
    pubsub1.get_message = AsyncMock(side_effect=first_pubsub_side_effect + [None] * 200)

    pubsub2 = AsyncMock()
    pubsub2.subscribe = AsyncMock()
    pubsub2.unsubscribe = AsyncMock()
    pubsub2.aclose = AsyncMock()
    pubsub2.get_message = AsyncMock(side_effect=second_pubsub_messages + [None] * 200)

    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock()
    mock_redis.pubsub = MagicMock(side_effect=[pubsub1, pubsub2])
    svc.async_redis = mock_redis
    return svc


class TestStreamLogDisconnectReconnectIntegration:
    """stream_log_file: 실제 disconnect→reconnect 이벤트 시퀀스 통합 검증"""

    @pytest.mark.asyncio
    async def test_stream_log_disconnect_reconnect_event_sequence(self):
        """
        pubsub.get_message: ConnectionError → None → __COMPLETED__ 시퀀스.
        LogService 인스턴스 직접 사용(mock 최소화).
        이벤트 시퀀스: connected → redis_disconnected → connected → completed 순서 검증.
        """
        svc = _build_service(
            first_pubsub_side_effect=[aioredis.ConnectionError("Redis down")],
            second_pubsub_messages=[_msg("__COMPLETED__")],
        )

        with patch("asyncio.sleep", new=AsyncMock()):
            events = await _collect(svc.stream_log_file("integ-runner-01"))

        # 이벤트가 수집되어야 함
        assert len(events) >= 3, f"이벤트 수 부족: {events}"

        # 각 이벤트 존재 확인
        assert "event: connected\ndata: ok\n\n" in events, "connected 이벤트 없음"
        assert "event: redis_disconnected\ndata: Redis not available\n\n" in events, \
            "redis_disconnected 이벤트 없음"
        assert "event: completed\ndata: completed\n\n" in events, "completed 이벤트 없음"

        # 시퀀스 순서 검증
        first_connected = events.index("event: connected\ndata: ok\n\n")
        dc_idx = events.index("event: redis_disconnected\ndata: Redis not available\n\n")
        connected_after_dc = [
            i for i, e in enumerate(events)
            if e == "event: connected\ndata: ok\n\n" and i > dc_idx
        ]

        assert first_connected < dc_idx, \
            f"초기 connected({first_connected})가 redis_disconnected({dc_idx})보다 뒤에 있음"
        assert connected_after_dc, \
            f"redis_disconnected 이후 connected 이벤트가 없음. 전체 이벤트: {events}"

        # 두 번째 pubsub이 실제로 생성됐는지 확인 (2회 호출)
        assert svc.async_redis.pubsub.call_count == 2, \
            f"pubsub 호출 횟수 오류: {svc.async_redis.pubsub.call_count} (기대: 2)"

    @pytest.mark.asyncio
    async def test_stream_merge_log_disconnect_reconnect_event_sequence(self):
        """
        stream_merge_log에서 동일한 disconnect → reconnect → connected 이벤트 전송 검증.
        """
        svc = _build_service(
            first_pubsub_side_effect=[aioredis.ConnectionError("Redis down")],
            second_pubsub_messages=[_msg("__MERGE_COMPLETED__")],
        )

        with patch("asyncio.sleep", new=AsyncMock()):
            events = await _collect(svc.stream_merge_log("integ-runner-01"))

        assert "event: connected\ndata: ok\n\n" in events, "connected 이벤트 없음"
        assert "event: redis_disconnected\ndata: Redis not available\n\n" in events, \
            "redis_disconnected 이벤트 없음"

        dc_idx = events.index("event: redis_disconnected\ndata: Redis not available\n\n")
        connected_after_dc = [
            i for i, e in enumerate(events)
            if e == "event: connected\ndata: ok\n\n" and i > dc_idx
        ]
        assert connected_after_dc, \
            f"redis_disconnected 이후 connected 이벤트가 없음. 전체 이벤트: {events}"

        assert svc.async_redis.pubsub.call_count == 2, \
            f"pubsub 호출 횟수 오류: {svc.async_redis.pubsub.call_count} (기대: 2)"
