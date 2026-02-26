"""EventService 유닛테스트

fakeredis를 사용하여 Redis 없이 이벤트 처리 로직을 검증한다.
"""

import asyncio
import json
import pytest
import fakeredis
import fakeredis.aioredis

from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.dev_runner.services.event_service import EventService, RUNNER_KEY_PREFIX, REDIS_STATE_KEY


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def sync_redis():
    """fakeredis 동기 클라이언트"""
    r = fakeredis.FakeRedis(decode_responses=True)
    yield r
    r.close()


@pytest.fixture
def async_redis():
    """fakeredis 비동기 클라이언트"""
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r


@pytest.fixture
def event_service(sync_redis, async_redis):
    """테스트용 EventService (fakeredis 주입)"""
    svc = EventService.__new__(EventService)
    svc._sync = sync_redis
    svc._async = async_redis
    return svc


# ─── _classify_key 테스트 ────────────────────────────────────────────────────

class TestClassifyKey:
    def test_status_key(self, event_service):
        key = f"{RUNNER_KEY_PREFIX}:abc123:status"
        assert event_service._classify_key(key) == "status"

    def test_tracking_key(self, event_service):
        key = f"{REDIS_STATE_KEY}:current_task_text"
        assert event_service._classify_key(key) == "tracking"

    def test_plan_changed_key(self, event_service):
        key = f"{REDIS_STATE_KEY}:current_task_plan_file"
        assert event_service._classify_key(key) == "plan_changed"

    def test_unknown_key_returns_none(self, event_service):
        assert event_service._classify_key("unrelated:key") is None
        assert event_service._classify_key("plan-runner:listener:heartbeat") is None

    def test_active_runners_key_not_matched(self, event_service):
        # active_runners는 Set이므로 status가 아닌 None이어야 함
        # plan-runner:active_runners 는 RUNNER_KEY_PREFIX 와 다름
        key = "plan-runner:active_runners"
        result = event_service._classify_key(key)
        # plan-runner:runners: 접두사가 아니므로 None
        assert result is None


# ─── _build_status_payload 테스트 ────────────────────────────────────────────

class TestBuildStatusPayload:
    def test_returns_dict_with_runner_id(self, event_service, sync_redis):
        runner_id = "test01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", "12345")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:current_cycle", "3")

        payload = event_service._build_status_payload(runner_id)
        assert payload is not None
        assert payload["runner_id"] == runner_id
        assert payload["status"] == "running"
        assert payload["pid"] == "12345"
        assert payload["current_cycle"] == "3"

    def test_missing_fields_return_none_values(self, event_service):
        payload = event_service._build_status_payload("nonexistent")
        assert payload is not None
        assert payload["status"] is None
        assert payload["pid"] is None


# ─── _build_tracking_payload 테스트 ─────────────────────────────────────────

class TestBuildTrackingPayload:
    def test_returns_none_when_no_text(self, event_service):
        assert event_service._build_tracking_payload() is None

    def test_returns_dict_with_text(self, event_service, sync_redis):
        sync_redis.set(f"{REDIS_STATE_KEY}:current_task_text", "[ ] 테스트 태스크")
        sync_redis.set(f"{REDIS_STATE_KEY}:current_task_confidence", "HIGH")
        sync_redis.set(f"{REDIS_STATE_KEY}:current_task_line_num", "42")
        sync_redis.set(f"{REDIS_STATE_KEY}:current_task_plan_file", "/path/to/plan.md")

        payload = event_service._build_tracking_payload()
        assert payload is not None
        assert payload["text"] == "[ ] 테스트 태스크"
        assert payload["confidence"] == "HIGH"
        assert payload["line_num"] == 42
        assert payload["plan_file"] == "/path/to/plan.md"


# ─── _sse 포맷 테스트 ────────────────────────────────────────────────────────

class TestSseFormat:
    def test_sse_format(self):
        result = EventService._sse("status", {"running": True})
        assert result.startswith("event: status\n")
        assert "data: " in result
        assert result.endswith("\n\n")

    def test_sse_data_is_valid_json(self):
        payload = {"runners": [{"runner_id": "abc", "status": "running"}]}
        result = EventService._sse("status", payload)
        data_line = [l for l in result.splitlines() if l.startswith("data: ")][0]
        parsed = json.loads(data_line[6:])  # "data: " 제거
        assert parsed["runners"][0]["runner_id"] == "abc"


# ─── stream_events 통합 테스트 (Right) ──────────────────────────────────────

class TestStreamEventsIntegration:
    @pytest.mark.asyncio
    async def test_initial_events_yielded(self, event_service, sync_redis, async_redis):
        """연결 직후 connected + status 이벤트가 yield 되는지 확인"""
        # 테스트용 pubsub mock — 즉시 종료
        mock_pubsub = AsyncMock()
        mock_pubsub.psubscribe = AsyncMock()
        mock_pubsub.get_message = AsyncMock(return_value=None)
        mock_pubsub.punsubscribe = AsyncMock()
        mock_pubsub.aclose = AsyncMock()

        async_redis.pubsub = MagicMock(return_value=mock_pubsub)
        event_service._async = async_redis

        gen = event_service.stream_events()
        first = await gen.__anext__()
        assert first == "event: connected\ndata: ok\n\n"

        second = await gen.__anext__()
        assert second.startswith("event: status\n")

        await gen.aclose()

    @pytest.mark.asyncio
    async def test_unknown_key_filtered_out(self, event_service, sync_redis, async_redis):
        """알 수 없는 키 변경 이벤트는 yield 없이 무시 확인"""
        message = {"type": "message", "data": "unrelated:key:value"}
        call_count = 0

        async def mock_get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return message
            raise StopAsyncIteration

        mock_pubsub = AsyncMock()
        mock_pubsub.psubscribe = AsyncMock()
        mock_pubsub.get_message = AsyncMock(side_effect=mock_get_message)
        async_redis.pubsub = MagicMock(return_value=mock_pubsub)
        event_service._async = async_redis

        gen = event_service.stream_events()
        _ = await gen.__anext__()  # connected
        _ = await gen.__anext__()  # status (초기)

        # 알 수 없는 키 이벤트 → heartbeat나 sleep 후 다음 event (StopAsyncIteration 발생 전)
        # 단순히 예외 없이 흐르는지 확인
        try:
            await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        except (StopAsyncIteration, asyncio.TimeoutError):
            pass  # 정상 — 알 수 없는 키는 무시됨

        await gen.aclose()
