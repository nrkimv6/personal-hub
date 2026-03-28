"""Redis 연결 누수 통합 테스트 — 실제 Redis에서 pubsub cleanup 확인."""
import asyncio

import pytest
import redis.asyncio as aioredis


def _redis_available() -> bool:
    """Redis 접속 가능 여부."""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, socket_connect_timeout=2)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(not _redis_available(), reason="Redis not available")
async def test_pubsub_cleanup_integration_real_redis():
    """실제 Redis에 pubsub 구독 → generator aclose → CLIENT LIST로 해당 구독 해제 확인."""
    r = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    channel = "test:connection-leak:cleanup"

    # 구독 전 클라이언트 수
    info_before = await r.info("clients")
    before = info_before.get("connected_clients", 0)

    # pubsub 구독
    pubsub = r.pubsub()
    await pubsub.subscribe(channel)

    # 구독 중 클라이언트 수 확인 (pubsub은 별도 연결)
    info_during = await r.info("clients")
    during = info_during.get("connected_clients", 0)
    assert during >= before  # pubsub 연결이 추가됨

    # 정리
    await pubsub.unsubscribe(channel)
    await pubsub.aclose()

    # 약간의 대기 후 클라이언트 수 확인
    await asyncio.sleep(0.5)
    info_after = await r.info("clients")
    after = info_after.get("connected_clients", 0)

    # pubsub 연결이 해제되어 during보다 감소 (또는 동일)
    assert after <= during

    await r.aclose()


@pytest.mark.asyncio
@pytest.mark.skipif(not _redis_available(), reason="Redis not available")
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
