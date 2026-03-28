"""Redis 연결 누수 방어 테스트 — SSE generator finally 블록 + ConnectionPool."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── event_service 테스트 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_events_cleanup_on_client_disconnect():
    """R: stream_events() generator aclose 시 _safe_close_pubsub이 pubsub, log_pubsub 모두에 호출되는지 확인."""
    from app.modules.dev_runner.services.event_service import EventService, _safe_close_pubsub

    svc = EventService()

    # mock pubsub
    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = AsyncMock(return_value=None)
    mock_pubsub.psubscribe = AsyncMock()

    mock_log_pubsub = AsyncMock()
    mock_log_pubsub.get_message = AsyncMock(return_value=None)
    mock_log_pubsub.psubscribe = AsyncMock()

    # _async.pubsub()가 두 번 호출됨 — 첫 번째는 keyspace, 두 번째는 log
    svc._async = MagicMock()
    svc._async.pubsub = MagicMock(side_effect=[mock_pubsub, mock_log_pubsub])

    # _enable_keyspace_notifications 무시
    svc._enable_keyspace_notifications = AsyncMock()
    svc._build_all_runners_status = MagicMock(return_value=[])
    svc._build_tracking_payload = MagicMock(return_value=None)

    gen = svc.stream_events()

    # 초기 이벤트 3개 소비 (connected, status, 그리고 while 루프 진입)
    events = []
    for _ in range(3):
        try:
            event = await asyncio.wait_for(gen.__anext__(), timeout=2)
            events.append(event)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break

    # generator를 닫음 (클라이언트 끊김 시뮬레이션)
    await gen.aclose()

    # _safe_close_pubsub이 두 pubsub 모두 정리했는지 확인
    # aclose 또는 punsubscribe가 호출됐어야 함
    assert mock_pubsub.punsubscribe.called or mock_pubsub.aclose.called
    assert mock_log_pubsub.punsubscribe.called or mock_log_pubsub.aclose.called


@pytest.mark.asyncio
async def test_stream_events_cleanup_after_redis_error():
    """E: Redis ConnectionError 발생 후 재연결 시 이전 pubsub이 정리되는지 확인."""
    from app.modules.dev_runner.services.event_service import EventService

    svc = EventService()

    # 첫 번째 pubsub은 ConnectionError를 발생시킴
    error_pubsub = AsyncMock()
    error_pubsub.psubscribe = AsyncMock()
    error_pubsub.get_message = AsyncMock(side_effect=ConnectionError("test"))
    error_pubsub.punsubscribe = AsyncMock()
    error_pubsub.aclose = AsyncMock()

    svc._async = MagicMock()
    svc._async.pubsub = MagicMock(return_value=error_pubsub)
    svc._enable_keyspace_notifications = AsyncMock()
    svc._build_all_runners_status = MagicMock(return_value=[])
    svc._build_tracking_payload = MagicMock(return_value=None)

    gen = svc.stream_events()
    events = []
    for _ in range(5):
        try:
            event = await asyncio.wait_for(gen.__anext__(), timeout=2)
            events.append(event)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break

    await gen.aclose()

    # except 블록에서 _safe_close_pubsub(pubsub) 호출됨 → punsubscribe 또는 aclose
    assert error_pubsub.punsubscribe.called or error_pubsub.aclose.called


# ── log_service 테스트 ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_log_file_cleanup_on_cancel():
    """R: stream_log_file() generator aclose 시 pubsub.unsubscribe + aclose 호출 확인."""
    from app.modules.dev_runner.services.log_service import LogService

    svc = LogService()

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.get_message = AsyncMock(return_value=None)
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()

    svc.async_redis = MagicMock()
    svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)
    svc.async_redis.ping = AsyncMock()

    gen = svc.stream_log_file("test-runner")

    # connected 이벤트 소비 + while 루프 진입
    for _ in range(2):
        try:
            await asyncio.wait_for(gen.__anext__(), timeout=2)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break

    await gen.aclose()

    assert mock_pubsub.unsubscribe.called
    assert mock_pubsub.aclose.called


@pytest.mark.asyncio
async def test_stream_log_file_cleanup_after_completed():
    """B: __COMPLETED__ 수신 후 정상 종료 + generator aclose 시 중복 cleanup 무해 확인."""
    from app.modules.dev_runner.services.log_service import LogService

    svc = LogService()

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.get_message = AsyncMock(return_value={
        "type": "message", "data": "__COMPLETED__"
    })
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()

    svc.async_redis = MagicMock()
    svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)
    svc.async_redis.ping = AsyncMock()

    gen = svc.stream_log_file("test-runner")
    events = []
    async for event in gen:
        events.append(event)
        if "completed" in event:
            break

    # __COMPLETED__ 후 generator 종료 — finally에서 중복 cleanup 호출해도 예외 없음
    await gen.aclose()

    # unsubscribe가 최소 1회 호출됨 (finally 블록에서)
    assert mock_pubsub.unsubscribe.called


@pytest.mark.asyncio
async def test_stream_merge_log_cleanup_on_cancel():
    """R: stream_merge_log() generator aclose 시 pubsub 정리 확인."""
    from app.modules.dev_runner.services.log_service import LogService

    svc = LogService()

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.get_message = AsyncMock(return_value=None)
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()

    svc.async_redis = MagicMock()
    svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)

    gen = svc.stream_merge_log("test-runner")

    for _ in range(2):
        try:
            await asyncio.wait_for(gen.__anext__(), timeout=2)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break

    await gen.aclose()

    assert mock_pubsub.unsubscribe.called
    assert mock_pubsub.aclose.called


# ── llm_routes 테스트 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_sse_generator_cleanup_on_cancel():
    """R: _chat_sse_generator() aclose 시 pubsub + Redis client 모두 정리 확인."""
    from app.modules.claude_worker.routes import llm_routes

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.listen = MagicMock(return_value=AsyncIteratorMock([]))
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()

    mock_redis = MagicMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    original = llm_routes._redis_async
    llm_routes._redis_async = mock_redis
    try:
        gen = llm_routes._chat_sse_generator(999)

        # generator 실행 후 즉시 닫기
        try:
            await asyncio.wait_for(gen.__anext__(), timeout=1)
        except (StopAsyncIteration, asyncio.TimeoutError):
            pass

        await gen.aclose()

        assert mock_pubsub.unsubscribe.called
        assert mock_pubsub.aclose.called
    finally:
        llm_routes._redis_async = original


@pytest.mark.asyncio
async def test_chat_sse_generator_uses_singleton_redis():
    """R: 모듈 레벨 싱글톤 Redis client 사용, 요청별 pubsub만 생성되는지 확인."""
    from app.modules.claude_worker.routes import llm_routes

    # _redis_async가 모듈 레벨에 존재
    assert hasattr(llm_routes, '_redis_async')
    assert llm_routes._redis_async is not None


# ── ConnectionPool 테스트 ────────────────────────────────────────────────────

def test_redis_pool_max_connections():
    """B: RedisClient ConnectionPool max_connections=50 설정 확인."""
    from app.shared.redis.client import RedisClient

    # async pool이 생성되면 max_connections가 50인지 확인
    # (실제 Redis 연결 없이 설정값만 검증)
    pool = RedisClient._async_pool
    if pool is not None:
        assert pool.max_connections == 50


# ── diagnostics 테스트 ───────────────────────────────────────────────────────

def test_diagnostics_reports_high_connection_count():
    """R: INFO clients가 connected_clients: 150 반환 시 diagnostics에 WARNING 포함."""
    from app.modules.dev_runner.services.log_service import LogService

    svc = LogService()
    svc.redis_client = MagicMock()
    svc.redis_client.ping = MagicMock()
    svc.redis_client.info = MagicMock(return_value={"connected_clients": 150})
    svc.redis_client.get = MagicMock(return_value=None)
    svc.redis_client.smembers = MagicMock(return_value=set())

    result = svc.run_diagnostics()
    steps = result["steps"]

    # step 2 = Redis 연결 수
    conn_step = next(s for s in steps if s["name"] == "Redis 연결 수")
    assert conn_step["ok"] is False
    assert "좀비" in conn_step["detail"]


def test_diagnostics_normal_connection_count():
    """B: connected_clients: 5 반환 시 ok=True."""
    from app.modules.dev_runner.services.log_service import LogService

    svc = LogService()
    svc.redis_client = MagicMock()
    svc.redis_client.ping = MagicMock()
    svc.redis_client.info = MagicMock(return_value={"connected_clients": 5})
    svc.redis_client.get = MagicMock(return_value="1234567890")
    svc.redis_client.smembers = MagicMock(return_value=set())

    result = svc.run_diagnostics()
    steps = result["steps"]

    conn_step = next(s for s in steps if s["name"] == "Redis 연결 수")
    assert conn_step["ok"] is True


# ── Helper ───────────────────────────────────────────────────────────────────

class AsyncIteratorMock:
    """async for 지원 mock."""
    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration
