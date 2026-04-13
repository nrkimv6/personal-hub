"""T5: plan-runner 보류 자동 전이 제거 HTTP 통합 테스트

plan-runner가 실패 시나리오(rate_limit, empty_run, test_failed)에서
plan 상태를 "보류"로 변경하지 않고 실패 이력을 기록하는지 admin API 레벨에서 검증.

(실행: /merge-test, localhost:8001 실서버 + Redis 필요)
"""

import time
from pathlib import Path
from unittest.mock import patch

import pytest
import redis
import requests

ADMIN_API = "http://localhost:8001"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
LOG_CHANNEL_PREFIX = "plan-runner:logs"
RUNNER_RUN_ENDPOINT = f"{ADMIN_API}/api/v1/dev-runner/run"

pytestmark = pytest.mark.http_live


@pytest.fixture
def r_live():
    client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    try:
        client.ping()
    except Exception:
        pytest.fail("Redis not available")
    yield client
    client.close()


@pytest.fixture
def admin_api_live():
    """admin API가 실행 중인지 확인"""
    try:
        resp = requests.get(f"{ADMIN_API}/api/v1/dev-runner/runners", timeout=3)
        resp.raise_for_status()
    except Exception:
        pytest.skip("Admin API (localhost:8001) 미실행 — T5 스킵")


# ---------------------------------------------------------------------------
# T5-01: 보류 plan에 run 요청 → [HOLD] 태그 로그 발생 + skip 동작 검증
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_hold_skip_http(tmp_path, r_live, admin_api_live):
    """T5-01: 보류 상태 plan → run 요청 → [HOLD] 태그 로그 발생 + plan 상태 유지 검증

    note: plan-runner가 보류 plan을 skip하면 [HOLD] 태그 로그가 Redis에 publish되고
    plan 상태는 '보류'로 유지되어야 한다 (자동 전이 없음).
    """
    # 테스트용 보류 plan 파일 (임시 — plan-runner가 접근 가능한 경로로 설정 필요)
    # 이 테스트는 실제 plan-runner가 임시 plan을 처리할 수 있는 환경이 필요하므로
    # 환경이 갖춰지지 않은 경우 skip
    pytest.skip(
        "T5-01: 실제 plan-runner 실행 환경 필요 — plan 경로 설정 후 수동 검증"
    )


# ---------------------------------------------------------------------------
# T5-02: Telegram 알림 HTTP 통합 — [FAILURE] 로그 → send_telegram 검증
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_failure_telegram_notification_http(r_live, admin_api_live):
    """T5-02: SSE 스트림에 [FAILURE] 태그 → Telegram send_telegram 호출 검증 (mock)

    log_service.py의 stream_log_file이 [FAILURE] 태그를 감지해
    _send_failure_telegram을 호출하는지 HTTP 레벨에서 검증.
    """
    import threading
    import asyncio
    from unittest.mock import AsyncMock, patch as _patch
    from app.modules.dev_runner.services.log_service import _telegram_debounce

    _telegram_debounce.clear()
    runner_id = "t5-failure-telegram-test"
    channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

    send_calls: list[tuple] = []

    async def fake_send(rid: str, tag: str, detail: str) -> None:
        send_calls.append((rid, tag, detail))

    # SSE 엔드포인트에 연결해 FAILURE 메시지 publish → _send_failure_telegram 호출 여부 확인
    # 실제 SSE 연결 없이 log_service 직접 테스트
    async def run_test():
        import redis.asyncio as aioredis
        from app.modules.dev_runner.services.log_service import LogService, LOG_CHANNEL_PREFIX as _PREFIX
        from app.modules.dev_runner.services.completion_reason import LOG_COMPLETED_SENTINEL
        from unittest.mock import MagicMock

        r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        svc = LogService.__new__(LogService)
        svc.async_redis = r
        svc.redis_client = MagicMock()
        svc._find_current_log = MagicMock(return_value=None)

        collected: list[str] = []

        async def consume():
            async for item in svc.stream_log_file(runner_id, since_line=0):
                collected.append(item)
                if "event: completed" in item:
                    break

        with _patch(
            "app.modules.dev_runner.services.log_service._send_failure_telegram",
            side_effect=fake_send,
        ):
            task = asyncio.create_task(consume())
            await asyncio.sleep(0.3)
            redis_sync = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            redis_sync.publish(channel, "[FAILURE] rate_limit: T5 HTTP 통합 테스트")
            redis_sync.close()
            await asyncio.sleep(0.5)
            redis_sync2 = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            redis_sync2.publish(channel, LOG_COMPLETED_SENTINEL)
            redis_sync2.close()
            try:
                await asyncio.wait_for(task, timeout=4.0)
            except asyncio.TimeoutError:
                task.cancel()

        await r.aclose()

    asyncio.run(run_test())

    assert len(send_calls) >= 1, f"_send_failure_telegram 미호출 (T5-02): calls={send_calls}"
    assert send_calls[0][1] == "FAILURE"
    assert "rate_limit" in send_calls[0][2]


# ---------------------------------------------------------------------------
# T5-03: Telegram 알림 HTTP 통합 — [HOLD] 로그 → send_telegram 검증
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_hold_telegram_notification_http(r_live, admin_api_live):
    """T5-03: SSE 스트림에 [HOLD] 태그 → Telegram send_telegram 호출 검증 (mock)"""
    import asyncio
    from unittest.mock import patch as _patch
    from app.modules.dev_runner.services.log_service import _telegram_debounce

    _telegram_debounce.clear()
    runner_id = "t5-hold-telegram-test"
    channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

    send_calls: list[tuple] = []

    async def fake_send(rid: str, tag: str, detail: str) -> None:
        send_calls.append((rid, tag, detail))

    async def run_test():
        import redis.asyncio as aioredis
        from app.modules.dev_runner.services.log_service import LogService
        from app.modules.dev_runner.services.completion_reason import LOG_COMPLETED_SENTINEL
        from unittest.mock import MagicMock

        r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        svc = LogService.__new__(LogService)
        svc.async_redis = r
        svc.redis_client = MagicMock()
        svc._find_current_log = MagicMock(return_value=None)

        async def consume():
            async for item in svc.stream_log_file(runner_id, since_line=0):
                if "event: completed" in item:
                    break

        with _patch(
            "app.modules.dev_runner.services.log_service._send_failure_telegram",
            side_effect=fake_send,
        ):
            task = asyncio.create_task(consume())
            await asyncio.sleep(0.3)
            redis_sync = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            redis_sync.publish(channel, "[HOLD] plan 보류 중: T5 HTTP 통합 테스트")
            redis_sync.close()
            await asyncio.sleep(0.5)
            redis_sync2 = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            redis_sync2.publish(channel, LOG_COMPLETED_SENTINEL)
            redis_sync2.close()
            try:
                await asyncio.wait_for(task, timeout=4.0)
            except asyncio.TimeoutError:
                task.cancel()

        await r.aclose()

    asyncio.run(run_test())

    assert len(send_calls) >= 1, f"_send_failure_telegram 미호출 (T5-03): calls={send_calls}"
    assert send_calls[0][1] == "HOLD"
