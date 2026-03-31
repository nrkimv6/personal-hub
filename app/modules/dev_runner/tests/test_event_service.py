"""EventService 유닛테스트

fakeredis를 사용하여 Redis 없이 이벤트 처리 로직을 검증한다.
"""

import asyncio
import json
import pytest
import fakeredis
import fakeredis.aioredis

from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.dev_runner.services.event_service import (
    EventService, RUNNER_KEY_PREFIX, REDIS_STATE_KEY,
    LOG_CHANNEL_PATTERN, MERGE_LOG_CHANNEL_PATTERN,
    _LOG_COMPLETED_SENTINEL, _MERGE_LOG_COMPLETED_SENTINEL,
)


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

    def test_build_status_payload_stopped_runner_plan_file_none_returns_none(self, event_service, sync_redis):
        """R: status=stopped + plan_file 키 없음 → plan_file is None (sentinel 아님)"""
        runner_id = "stopped01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        payload = event_service._build_status_payload(runner_id)
        assert payload is not None
        assert payload["plan_file"] is None

    def test_build_status_payload_running_runner_plan_file_none_returns_none(self, event_service, sync_redis):
        """R: status=running + plan_file 키 없음 → None 반환 (sentinel fallback 제거)"""
        runner_id = "running01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        payload = event_service._build_status_payload(runner_id)
        assert payload is not None
        assert payload["plan_file"] is None

    def test_build_status_payload_running_with_explicit_sentinel(self, event_service, sync_redis):
        """R: plan_file에 __ALL_PLANS__ 명시 → 그대로 전달"""
        from app.modules.dev_runner.services.event_service import PLAN_FILE_ALL
        runner_id = "running01b"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", PLAN_FILE_ALL)
        payload = event_service._build_status_payload(runner_id)
        assert payload is not None
        assert payload["plan_file"] == PLAN_FILE_ALL

    def test_build_status_payload_plan_file_empty_string_returns_none(self, event_service, sync_redis):
        """B: plan_file="" (falsy) → None 반환"""
        runner_id = "running01c"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "")
        payload = event_service._build_status_payload(runner_id)
        assert payload is not None
        assert payload["plan_file"] is None

    def test_build_status_payload_running_runner_plan_file_set_returns_value(self, event_service, sync_redis):
        """R: status=running + plan_file 정상값 → 그대로 반환"""
        runner_id = "running02"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "feature-x.md")
        payload = event_service._build_status_payload(runner_id)
        assert payload is not None
        assert payload["plan_file"] == "feature-x.md"

    def test_build_status_payload_stopped_runner_branch_set_still_none(self, event_service, sync_redis):
        """B: status=stopped + branch 있음 + plan_file 없음 → plan_file is None (branch로 fallback 안 됨)"""
        runner_id = "stopped02"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "impl/some-feature")
        payload = event_service._build_status_payload(runner_id)
        assert payload is not None
        assert payload["plan_file"] is None

    def test_build_status_payload_includes_trigger_field(self, event_service, sync_redis):
        """R: trigger 키 있는 runner → payload에 trigger 필드 포함"""
        runner_id = "triggered01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "manual")
        payload = event_service._build_status_payload(runner_id)
        assert payload is not None
        assert payload["trigger"] == "manual"

    def test_build_status_payload_trigger_none_when_key_missing(self, event_service, sync_redis):
        """B: trigger Redis 키 없음 → payload["trigger"] is None"""
        runner_id = "triggered02"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        # trigger 키 미설정
        payload = event_service._build_status_payload(runner_id)
        assert payload is not None
        assert payload["trigger"] is None


# ─── _build_all_runners_status 필터링 테스트 ─────────────────────────────────

class TestBuildAllRunnersStatus:
    def _register_runner(self, redis, runner_id: str, trigger: str | None = None, status: str = "running"):
        redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", status)
        if trigger is not None:
            redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", trigger)
        redis.sadd("plan-runner:active_runners", runner_id)

    def test_build_all_runners_excludes_tc_trigger(self, event_service, sync_redis):
        """R: trigger="tc:test" runner 등록 → _build_all_runners_status() 결과에 미포함"""
        self._register_runner(sync_redis, "tc_runner01", trigger="tc:test")
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "tc_runner01" not in ids

    def test_build_all_runners_includes_normal_trigger(self, event_service, sync_redis):
        """R: trigger="manual" runner → 화이트리스트에 없으므로 결과에 미포함"""
        self._register_runner(sync_redis, "manual_runner01", trigger="manual")
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "manual_runner01" not in ids

    def test_build_all_runners_includes_trigger_none(self, event_service, sync_redis):
        """B: trigger 키 없음(None) → 화이트리스트에 없으므로 미포함"""
        self._register_runner(sync_redis, "notrigger_runner01", trigger=None)
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "notrigger_runner01" not in ids

    def test_build_all_runners_includes_trigger_empty(self, event_service, sync_redis):
        """B: trigger="" → 화이트리스트에 없으므로 미포함"""
        self._register_runner(sync_redis, "emptytrigger_runner01", trigger="")
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "emptytrigger_runner01" not in ids

    def test_build_all_runners_includes_user_trigger(self, event_service, sync_redis):
        """R: trigger="user" runner → 결과에 포함"""
        self._register_runner(sync_redis, "user_runner01", trigger="user")
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "user_runner01" in ids

    def test_build_all_runners_includes_user_all_trigger(self, event_service, sync_redis):
        """R: trigger="user:all" runner → 결과에 포함"""
        self._register_runner(sync_redis, "userall_runner01", trigger="user:all")
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "userall_runner01" in ids

    def test_build_all_runners_excludes_api_trigger(self, event_service, sync_redis):
        """R: trigger="api" runner → 화이트리스트에 없으므로 미포함"""
        self._register_runner(sync_redis, "api_runner01", trigger="api")
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "api_runner01" not in ids

    def test_build_all_runners_excludes_trigger_tc_prefix_only(self, event_service, sync_redis):
        """B: trigger="tc:" (접두사만, 값 없음) → 필터링됨"""
        self._register_runner(sync_redis, "tconly_runner01", trigger="tc:")
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "tconly_runner01" not in ids

    def test_build_all_runners_mixed(self, event_service, sync_redis):
        """R: tc: runner + 일반 runner 혼재 → 일반 runner만 반환"""
        self._register_runner(sync_redis, "vis_runner01", trigger="user")
        self._register_runner(sync_redis, "invis_runner01", trigger="tc:pytest")
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "vis_runner01" in ids
        assert "invis_runner01" not in ids


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


# ─── _extract_runner_id_from_channel 테스트 ──────────────────────────────────

class TestExtractRunnerIdFromChannel:
    def test_extract_runner_id_from_channel_right(self, event_service):
        """R: 정상 로그 채널 → runner_id 반환"""
        result = event_service._extract_runner_id_from_channel("plan-runner:logs:abc123")
        assert result == "abc123"

    def test_extract_runner_id_from_channel_merge(self, event_service):
        """R: 머지 로그 채널 → runner_id 반환"""
        result = event_service._extract_runner_id_from_channel("plan-runner:merge-log:def456")
        assert result == "def456"

    def test_extract_runner_id_from_channel_boundary_empty(self, event_service):
        """B: 빈 문자열 및 콜론 없는 문자열 → None 반환"""
        assert event_service._extract_runner_id_from_channel("") is None
        assert event_service._extract_runner_id_from_channel("nocolon") is None

    def test_extract_runner_id_from_channel_boundary_trailing_colon(self, event_service):
        """B: 콜론으로 끝나는 채널 (runner_id 빈값) → None 반환"""
        result = event_service._extract_runner_id_from_channel("plan-runner:logs:")
        assert result is None


# ─── stream_events 로그 통합 테스트 ─────────────────────────────────────────

def _make_dual_pubsub_mocks(ks_messages=None, log_messages=None):
    """keyspace/log pubsub용 별도 mock 쌍 생성 헬퍼."""
    mock_ks = AsyncMock()
    mock_ks.psubscribe = AsyncMock()
    mock_ks.punsubscribe = AsyncMock()
    mock_ks.aclose = AsyncMock()
    mock_ks.get_message = AsyncMock(
        side_effect=(ks_messages + [None] * 100) if ks_messages else None,
        return_value=None if not ks_messages else None,
    )
    if not ks_messages:
        mock_ks.get_message = AsyncMock(return_value=None)

    mock_log = AsyncMock()
    mock_log.psubscribe = AsyncMock()
    mock_log.punsubscribe = AsyncMock()
    mock_log.aclose = AsyncMock()
    if not log_messages:
        mock_log.get_message = AsyncMock(return_value=None)
    else:
        mock_log.get_message = AsyncMock(side_effect=log_messages + [None] * 100)

    call_count = 0
    def pubsub_factory():
        nonlocal call_count
        call_count += 1
        return mock_ks if call_count <= 1 else mock_log

    return mock_ks, mock_log, pubsub_factory


async def _collect_events(gen, count: int, timeout: float = 2.0) -> list[str]:
    """제너레이터에서 최대 count개 이벤트를 수집"""
    events = []
    for _ in range(count):
        try:
            event = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
            events.append(event)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break
    return events


class TestStreamEventsLogIntegration:
    @pytest.mark.asyncio
    async def test_stream_events_log_message_yielded(self, event_service, async_redis):
        """R: 로그 pubsub 메시지 → event: log + runner_id + line 수신"""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:runner01",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": "hello world",
        }
        _, _, factory = _make_dual_pubsub_mocks(log_messages=[log_msg])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 4)
        await gen.aclose()

        log_events = [e for e in events if e.startswith("event: log\n")]
        assert len(log_events) >= 1
        data = json.loads(log_events[0].split("data: ")[1].split("\n")[0])
        assert data["runner_id"] == "runner01"
        assert data["line"] == "hello world"

    @pytest.mark.asyncio
    async def test_stream_events_log_completed_signal(self, event_service, async_redis):
        """R: __COMPLETED__ → event: log_completed + runner_id"""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:runner02",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": _LOG_COMPLETED_SENTINEL,
        }
        _, _, factory = _make_dual_pubsub_mocks(log_messages=[log_msg])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 4)
        await gen.aclose()

        completed = [e for e in events if e.startswith("event: log_completed\n")]
        assert len(completed) >= 1
        data = json.loads(completed[0].split("data: ")[1].split("\n")[0])
        assert data["runner_id"] == "runner02"

    @pytest.mark.asyncio
    async def test_stream_events_merge_log_message(self, event_service, async_redis):
        """R: 머지 로그 메시지 → event: merge_log"""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:merge-log:runner03",
            "pattern": MERGE_LOG_CHANNEL_PATTERN,
            "data": "Merging branch impl/foo",
        }
        _, _, factory = _make_dual_pubsub_mocks(log_messages=[log_msg])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 4)
        await gen.aclose()

        merge_events = [e for e in events if e.startswith("event: merge_log\n")]
        assert len(merge_events) >= 1
        data = json.loads(merge_events[0].split("data: ")[1].split("\n")[0])
        assert data["runner_id"] == "runner03"
        assert data["line"] == "Merging branch impl/foo"

    @pytest.mark.asyncio
    async def test_stream_events_merge_log_completed_signal(self, event_service, async_redis):
        """R: __MERGE_COMPLETED__ → event: merge_log_completed"""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:merge-log:runner04",
            "pattern": MERGE_LOG_CHANNEL_PATTERN,
            "data": _MERGE_LOG_COMPLETED_SENTINEL,
        }
        _, _, factory = _make_dual_pubsub_mocks(log_messages=[log_msg])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 4)
        await gen.aclose()

        completed = [e for e in events if e.startswith("event: merge_log_completed\n")]
        assert len(completed) >= 1
        data = json.loads(completed[0].split("data: ")[1].split("\n")[0])
        assert data["runner_id"] == "runner04"

    @pytest.mark.asyncio
    async def test_stream_events_existing_keyspace_events_still_work(self, event_service, async_redis, sync_redis):
        """R: 로그 통합 후에도 status 이벤트 정상 동작 회귀 확인"""
        runner_id = "runner05"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.sadd("plan-runner:active_runners", runner_id)

        ks_msg = {
            "type": "message",
            "data": f"{RUNNER_KEY_PREFIX}:{runner_id}:status",
        }
        _, _, factory = _make_dual_pubsub_mocks(ks_messages=[ks_msg])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 5)
        await gen.aclose()

        status_events = [e for e in events if e.startswith("event: status\n")]
        assert len(status_events) >= 1

    @pytest.mark.asyncio
    async def test_stream_events_log_and_keyspace_concurrent(self, event_service, async_redis, sync_redis):
        """B: keyspace 이벤트와 로그 이벤트가 동시 도착 → 둘 다 누락 없이 yield"""
        runner_id = "runner06"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")

        ks_msg = {"type": "message", "data": f"{RUNNER_KEY_PREFIX}:{runner_id}:status"}
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:runner06",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": "concurrent log line",
        }
        _, _, factory = _make_dual_pubsub_mocks(ks_messages=[ks_msg], log_messages=[log_msg])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 6)
        await gen.aclose()

        event_types = set()
        for e in events:
            for etype in ("connected", "status", "log", "tracking"):
                if e.startswith(f"event: {etype}\n"):
                    event_types.add(etype)
        assert "status" in event_types
        assert "log" in event_types

    @pytest.mark.asyncio
    async def test_stream_events_log_empty_data(self, event_service, async_redis):
        """E: 로그 데이터가 빈 문자열 → 크래시 없이 무시"""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:runner07",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": "",
        }
        _, _, factory = _make_dual_pubsub_mocks(log_messages=[log_msg])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 3)
        await gen.aclose()

        log_events = [e for e in events if e.startswith("event: log\n")]
        assert len(log_events) == 0

    @pytest.mark.asyncio
    async def test_stream_events_log_pubsub_redis_disconnect(self, event_service, async_redis):
        """E: 로그 pubsub Redis 연결 끊김 → redis_disconnected 이벤트 yield"""
        import redis.asyncio as aioredis

        mock_ks = AsyncMock()
        mock_ks.psubscribe = AsyncMock()
        mock_ks.punsubscribe = AsyncMock()
        mock_ks.aclose = AsyncMock()
        mock_ks.get_message = AsyncMock(return_value=None)

        log_called = 0
        async def log_get_message_raise(**kwargs):
            nonlocal log_called
            log_called += 1
            if log_called == 1:
                raise aioredis.ConnectionError("log redis disconnected")
            return None

        mock_log = AsyncMock()
        mock_log.psubscribe = AsyncMock()
        mock_log.punsubscribe = AsyncMock()
        mock_log.aclose = AsyncMock()
        mock_log.get_message = AsyncMock(side_effect=log_get_message_raise)

        pubsub_call = 0
        def factory():
            nonlocal pubsub_call
            pubsub_call += 1
            return mock_ks if pubsub_call % 2 == 1 else mock_log

        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 5)
        await gen.aclose()

        disconnected = [e for e in events if "redis_disconnected" in e]
        assert len(disconnected) >= 1

    @pytest.mark.asyncio
    async def test_stream_events_log_pubsub_reconnect_after_none(self, event_service, async_redis):
        """E(Existence): log_pubsub 에러 후 log_pubsub=None 설정 → 다음 루프에서 pubsub() 재호출 확인"""
        import redis.asyncio as aioredis

        # log_pubsub 에러 후 pubsub()이 추가 호출되는지 추적
        pubsub_call_count = 0

        mock_ks = AsyncMock()
        mock_ks.psubscribe = AsyncMock()
        mock_ks.punsubscribe = AsyncMock()
        mock_ks.aclose = AsyncMock()
        mock_ks.get_message = AsyncMock(return_value=None)

        log1_called = 0
        async def log1_raise(**kwargs):
            nonlocal log1_called
            log1_called += 1
            if log1_called == 1:
                raise aioredis.ConnectionError("disconnected")
            return None

        mock_log1 = AsyncMock()
        mock_log1.psubscribe = AsyncMock()
        mock_log1.punsubscribe = AsyncMock()
        mock_log1.aclose = AsyncMock()
        mock_log1.get_message = AsyncMock(side_effect=log1_raise)

        def factory():
            nonlocal pubsub_call_count
            pubsub_call_count += 1
            # 1: ks, 2: log1(에러 발생), 3+: 재연결 pubsubs
            if pubsub_call_count == 1:
                return mock_ks
            return mock_log1  # 재연결에도 동일한 mock (에러 안 나는 두 번째 호출은 None 반환)

        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 3)
        await gen.aclose()

        # ConnectionError 후 redis_disconnected 이벤트 yield + 초기 2개 pubsub 생성 확인
        assert any("redis_disconnected" in e for e in events)
        assert pubsub_call_count >= 2  # 최소 ks + log_pubsub 초기 생성


# ─── MERGE 라인 이중 경로 검증 ───────────────────────────────────────────────

class TestMergeLineChannelRouting:
    @pytest.mark.asyncio
    async def test_stream_events_merge_completed_with_status(self, event_service, async_redis):
        """R: __MERGE_COMPLETED__:FAILED → merge_log_completed 이벤트에 status='failed' 포함"""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:merge-log:runner10",
            "pattern": MERGE_LOG_CHANNEL_PATTERN,
            "data": _MERGE_LOG_COMPLETED_SENTINEL + ":FAILED",
        }
        _, _, factory = _make_dual_pubsub_mocks(log_messages=[log_msg])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 4)
        await gen.aclose()

        completed = [e for e in events if e.startswith("event: merge_log_completed\n")]
        assert len(completed) >= 1
        data = json.loads(completed[0].split("data: ")[1].split("\n")[0])
        assert data["runner_id"] == "runner10"
        assert data["status"] == "failed"

    @pytest.mark.asyncio
    async def test_stream_events_log_completed_with_status(self, event_service, async_redis):
        """R: __COMPLETED__:FAILED → log_completed 이벤트에 status='failed' 포함"""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:runner11",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": _LOG_COMPLETED_SENTINEL + ":FAILED",
        }
        _, _, factory = _make_dual_pubsub_mocks(log_messages=[log_msg])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 4)
        await gen.aclose()

        completed = [e for e in events if e.startswith("event: log_completed\n")]
        assert len(completed) >= 1
        data = json.loads(completed[0].split("data: ")[1].split("\n")[0])
        assert data["runner_id"] == "runner11"
        assert data["status"] == "failed"

    @pytest.mark.asyncio
    async def test_merge_line_in_log_channel_yields_log_event(self, event_service, async_redis):
        """R: plan-runner:logs:{id}에 [MERGE] 라인 도착 시 event: log 로 전달됨 (백엔드는 필터링 안 함)."""
        merge_line = "[12:34:56] [MERGE] [INFO] execute_merge: project_dir=D:/foo, branch=impl/bar"
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:r1",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": merge_line,
        }
        _, _, factory = _make_dual_pubsub_mocks(log_messages=[log_msg])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 4)
        await gen.aclose()

        log_events = [e for e in events if e.startswith("event: log\n")]
        assert len(log_events) >= 1
        data = json.loads(log_events[0].split("data: ")[1].split("\n")[0])
        assert data["runner_id"] == "r1"
        assert "[MERGE]" in data["line"]

    @pytest.mark.asyncio
    async def test_merge_line_separate_events_from_two_channels(self, event_service, async_redis):
        """R: 동일 MERGE 라인이 logs:{id}와 merge-log:{id} 양쪽에 도착 시 각각 log, merge_log 이벤트로 분리됨."""
        merge_line = "[12:34:56] [MERGE] [INFO] execute_merge: project_dir=D:/foo"
        msg_log = {
            "type": "pmessage",
            "channel": "plan-runner:logs:r2",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": merge_line,
        }
        msg_merge = {
            "type": "pmessage",
            "channel": "plan-runner:merge-log:r2",
            "pattern": MERGE_LOG_CHANNEL_PATTERN,
            "data": merge_line,
        }
        # 두 메시지를 순서대로 log pubsub 에서 반환
        _, _, factory = _make_dual_pubsub_mocks(log_messages=[msg_log, msg_merge])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 6)
        await gen.aclose()

        log_events = [e for e in events if e.startswith("event: log\n")]
        merge_events = [e for e in events if e.startswith("event: merge_log\n")]

        # 백엔드는 두 채널 모두 그대로 전달 (필터링은 프론트에서)
        assert len(log_events) >= 1
        assert len(merge_events) >= 1

        log_data = json.loads(log_events[0].split("data: ")[1].split("\n")[0])
        merge_data = json.loads(merge_events[0].split("data: ")[1].split("\n")[0])
        assert log_data["line"] == merge_line
        assert merge_data["line"] == merge_line
