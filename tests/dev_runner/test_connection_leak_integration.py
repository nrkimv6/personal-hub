"""Redis 연결 누수 통합 테스트 — 실제 Redis에서 pubsub cleanup 확인."""
import asyncio
import uuid

import pytest
import redis.asyncio as aioredis


@pytest.mark.asyncio
async def test_pubsub_cleanup_integration_real_redis():
    """실제 Redis에 pubsub 구독 후 unsubscribe/aclose 시 채널 subscriber가 0으로 복구되는지 확인."""
    r = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    channel = f"test:connection-leak:cleanup:{uuid.uuid4().hex}"

    # pubsub 구독
    pubsub = r.pubsub()
    await pubsub.subscribe(channel)

    # 구독 중에는 해당 채널 subscriber가 1 이상이어야 함
    during_numsub = (await r.pubsub_numsub(channel))[0][1]
    assert during_numsub >= 1

    # 정리
    await pubsub.unsubscribe(channel)
    await pubsub.aclose()

    # unsubscribe 반영이 비동기적으로 지연될 수 있어 짧게 폴링
    after_numsub = None
    for _ in range(10):
        after_numsub = (await r.pubsub_numsub(channel))[0][1]
        if after_numsub == 0:
            break
        await asyncio.sleep(0.2)

    assert after_numsub == 0, f"unsubscribe/aclose 후 subscriber 잔존: channel={channel}, numsub={after_numsub}"

    await r.aclose()


@pytest.mark.asyncio
async def test_sse_disconnect_no_connection_leak_integration():
    """event_service stream_events() 시작 → generator aclose → 연결 수 증가하지 않음 확인."""
    r = aioredis.Redis(host="localhost", port=6379, decode_responses=True)

    info_before = await r.info("clients")
    before = info_before.get("connected_clients", 0)

    from app.modules.dev_runner.services.event_service import EventService
    svc = EventService()
    async def _noop(): pass
    svc._enable_keyspace_notifications = _noop
    svc._build_all_runners_status = lambda: []
    svc._build_tracking_payload = lambda: None

    gen = svc.stream_events()

    # 초기 이벤트 소비
    events = []
    for _ in range(3):
        try:
            event = await asyncio.wait_for(gen.__anext__(), timeout=3)
            events.append(event)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break

    # generator 닫기 (클라이언트 끊김)
    await gen.aclose()
    await asyncio.sleep(1)

    info_after = await r.info("clients")
    after = info_after.get("connected_clients", 0)

    # 연결 수가 크게 증가하지 않음 (±2 허용 — 다른 프로세스의 영향)
    assert after <= before + 2, f"연결 누수 의심: before={before}, after={after}"

    await r.aclose()
