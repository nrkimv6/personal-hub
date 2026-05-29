"""stream_events 통합 테스트

EventService.stream_events() 흐름 검증:
- TestStreamEventsIntegration: 초기 이벤트, 알 수 없는 키 필터링
- TestStreamEventsLogIntegration: 로그 pubsub 이벤트 처리
- TestStreamEventsFileFallback: 파일 폴링 fallback
- TestMergeLineChannelRouting: merge 채널 라우팅 + 완료 이벤트 파싱

외부 Redis 불필요 — fakeredis + mock pubsub 사용.
"""

import asyncio
import json
import pytest

from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.dev_runner.services.event_service import (
    EventService,
    RUNNER_KEY_PREFIX,
    LOG_CHANNEL_PATTERN,
    MERGE_LOG_CHANNEL_PATTERN,
    _LOG_COMPLETED_SENTINEL,
    _MERGE_LOG_COMPLETED_SENTINEL,
    FILE_POLL_TIMEOUT,
    FILE_POLL_INTERVAL,
)


# ─── 공통 헬퍼 ───────────────────────────────────────────────────────────────

def _make_dual_pubsub_mocks(ks_messages=None, log_messages=None):
    """keyspace/log pubsub용 별도 mock 쌍 생성 헬퍼."""
    mock_ks = AsyncMock()
    mock_ks.psubscribe = AsyncMock()
    mock_ks.punsubscribe = AsyncMock()
    mock_ks.aclose = AsyncMock()
    if not ks_messages:
        mock_ks.get_message = AsyncMock(return_value=None)
    else:
        mock_ks.get_message = AsyncMock(side_effect=ks_messages + [None] * 100)

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


# ─── TestStreamEventsIntegration ─────────────────────────────────────────────

class TestStreamEventsIntegration:
    @pytest.mark.asyncio
    async def test_enable_keyspace_notifications_right_sets_notify_keyspace_events(self, event_service, async_redis):
        """R: keyspace notifications 설정이 KEx$로 수행되는지 검증."""
        mock_config_set = AsyncMock(return_value=True)
        async_redis.config_set = mock_config_set
        event_service._async = async_redis

        await event_service._enable_keyspace_notifications()

        mock_config_set.assert_awaited_once_with("notify-keyspace-events", "KEx$")

    @pytest.mark.asyncio
    async def test_enable_keyspace_notifications_error_ignores_config_failure(self, event_service, async_redis):
        """E: Redis CONFIG SET 실패가 스트림 초기화를 죽이지 않는지 검증."""
        async def _raise(*args, **kwargs):
            raise RuntimeError("config disabled")

        async_redis.config_set = AsyncMock(side_effect=_raise)
        event_service._async = async_redis

        await event_service._enable_keyspace_notifications()

    @pytest.mark.asyncio
    async def test_initial_events_yielded(self, event_service, sync_redis, async_redis):
        """연결 직후 connected + status 이벤트가 yield 되는지 확인"""
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

        assert "event: connected" in first
        assert "event: status" in second

        await gen.aclose()

    @pytest.mark.asyncio
    async def test_initial_status_event_includes_merge_recovery_fields(self, event_service, sync_redis, async_redis):
        """R: 초기 status snapshot이 merge 복구용 필드를 포함한다."""
        runner_id = "runner-merge-status"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", "/tmp/wt/runner-merge-status")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage", "post_review")
        sync_redis.sadd("plan-runner:active_runners", runner_id)

        mock_pubsub = AsyncMock()
        mock_pubsub.psubscribe = AsyncMock()
        mock_pubsub.get_message = AsyncMock(return_value=None)
        mock_pubsub.punsubscribe = AsyncMock()
        mock_pubsub.aclose = AsyncMock()

        async_redis.pubsub = MagicMock(return_value=mock_pubsub)
        event_service._async = async_redis

        gen = event_service.stream_events()
        first = await gen.__anext__()
        second = await gen.__anext__()
        await gen.aclose()

        assert first == "event: connected\ndata: ok\n\n"
        assert second.startswith("event: status\n")
        payload = json.loads(second.split("data: ", 1)[1].split("\n", 1)[0])
        runners = payload["runners"]
        matched = next(r for r in runners if r["runner_id"] == runner_id)
        assert matched["worktree_path"] == "/tmp/wt/runner-merge-status"
        assert matched["merge_status"] == "merged"
        assert matched["stop_stage"] == "post_review"

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

        try:
            await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        except (StopAsyncIteration, asyncio.TimeoutError):
            pass  # 정상 — 알 수 없는 키는 무시됨

        await gen.aclose()


# ─── TestStreamEventsLogIntegration ──────────────────────────────────────────

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
        assert data["status"] == "success"
        assert data["reason"] == "completed"

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
        assert data["status"] == "success"
        assert data["reason"] == "completed"

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
    async def test_stream_events_log_multiline_payload_as_object(self, event_service, async_redis):
        """멀티라인 로그는 line={text,meta} 객체 포맷으로 전달된다."""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:runner-multi",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": "[12:00:00] [RESULT] line-1\nline-2\nline-3",
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
        assert isinstance(data["line"], dict)
        assert data["line"]["text"].startswith("[12:00:00] [RESULT] line-1")
        assert data["line"]["meta"]["multiline"] is True
        assert data["line"]["meta"]["line_count"] == 3

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


# ─── TestStreamEventsFileFallback ────────────────────────────────────────────

class TestStreamEventsFileFallback:
    @staticmethod
    def _install_idle_dual_pubsub(async_redis, log_get_message=None, ks_get_message=None):
        mock_ks = AsyncMock()
        mock_ks.psubscribe = AsyncMock()
        mock_ks.punsubscribe = AsyncMock()
        mock_ks.aclose = AsyncMock()
        mock_ks.get_message = AsyncMock(side_effect=ks_get_message) if ks_get_message else AsyncMock(return_value=None)

        mock_log = AsyncMock()
        mock_log.psubscribe = AsyncMock()
        mock_log.punsubscribe = AsyncMock()
        mock_log.aclose = AsyncMock()
        mock_log.get_message = AsyncMock(side_effect=log_get_message) if log_get_message else AsyncMock(return_value=None)

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return mock_ks if call_count <= 1 else mock_log

        async_redis.pubsub = MagicMock(side_effect=factory)
        return mock_ks, mock_log

    @pytest.mark.asyncio
    async def test_stream_events_fallback_emits_file_delta_when_pubsub_idle(
        self,
        event_service,
        async_redis,
        sync_redis,
        tmp_path,
    ):
        """R: pub/sub 무수신 상태에서 파일 증가분이 event: log로 전달된다."""
        runner_id = "fb-runner-01"
        log_file = tmp_path / "runner01.log"
        log_file.write_text("boot line\n", encoding="utf-8")

        sync_redis.sadd("plan-runner:active_runners", runner_id)
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path", str(log_file))

        self._install_idle_dual_pubsub(async_redis)
        event_service._async = async_redis
        event_service._file_poll_timeout = 0.0
        event_service._file_poll_interval_sec = 0.0

        gen = event_service.stream_events()
        _ = await gen.__anext__()  # connected
        _ = await gen.__anext__()  # status

        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write("line from fallback\n")

        events = await _collect_events(gen, 4, timeout=1.2)
        await gen.aclose()

        log_events = [e for e in events if e.startswith("event: log\n")]
        assert len(log_events) >= 1
        payloads = [json.loads(e.split("data: ")[1].split("\n")[0]) for e in log_events]
        assert any(p["runner_id"] == runner_id and p["line"] == "line from fallback" for p in payloads)

    @pytest.mark.asyncio
    async def test_stream_events_fallback_skips_invisible_runner(
        self,
        event_service,
        async_redis,
        sync_redis,
        tmp_path,
    ):
        """R: visible=False(trigger=api) runner는 fallback 대상에서 제외된다."""
        runner_id = "fb-hidden-01"
        log_file = tmp_path / "runner-hidden.log"
        log_file.write_text("boot line\nhidden live line\n", encoding="utf-8")

        sync_redis.sadd("plan-runner:active_runners", runner_id)
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "api")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path", str(log_file))

        self._install_idle_dual_pubsub(async_redis)
        event_service._async = async_redis
        event_service._file_poll_timeout = 0.0
        event_service._file_poll_interval_sec = 0.0

        gen = event_service.stream_events()
        events = await _collect_events(gen, 4, timeout=0.6)
        await gen.aclose()

        log_events = [e for e in events if e.startswith("event: log\n")]
        assert len(log_events) == 0

    @pytest.mark.asyncio
    async def test_stream_events_fallback_then_same_pubsub_line_is_deduped(
        self,
        event_service,
        async_redis,
        sync_redis,
        tmp_path,
    ):
        """R: fallback으로 주입된 동일 라인이 이후 pub/sub로 와도 log 중복 발행되지 않는다."""
        runner_id = "fb-dedup-01"
        duplicate_line = "same line from fallback and pubsub"
        log_file = tmp_path / "runner-dedup.log"
        log_file.write_text("boot\n", encoding="utf-8")

        sync_redis.sadd("plan-runner:active_runners", runner_id)
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path", str(log_file))

        emit_pubsub_duplicate = False

        async def log_get_message(**kwargs):
            nonlocal emit_pubsub_duplicate
            if emit_pubsub_duplicate:
                emit_pubsub_duplicate = False
                return {
                    "type": "pmessage",
                    "channel": f"plan-runner:logs:{runner_id}",
                    "pattern": LOG_CHANNEL_PATTERN,
                    "data": duplicate_line,
                }
            return None

        self._install_idle_dual_pubsub(async_redis, log_get_message=log_get_message)
        event_service._async = async_redis
        event_service._file_poll_timeout = 0.0
        event_service._file_poll_interval_sec = 0.0

        gen = event_service.stream_events()
        _ = await gen.__anext__()  # connected
        _ = await gen.__anext__()  # status

        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write(f"{duplicate_line}\n")

        fallback_events = await _collect_events(gen, 5, timeout=1.2)
        fallback_log_payloads = [
            json.loads(e.split("data: ")[1].split("\n")[0])
            for e in fallback_events
            if e.startswith("event: log\n")
        ]
        assert any(p["line"] == duplicate_line for p in fallback_log_payloads)

        emit_pubsub_duplicate = True
        after_pubsub_events = await _collect_events(gen, 3, timeout=0.8)
        after_pubsub_payloads = [
            json.loads(e.split("data: ")[1].split("\n")[0])
            for e in after_pubsub_events
            if e.startswith("event: log\n")
        ]
        assert all(p["line"] != duplicate_line for p in after_pubsub_payloads)

        await gen.aclose()

    @pytest.mark.asyncio
    async def test_structured_event_cross_sse_history_payload_match(
        self,
        event_service,
        async_redis,
        sync_redis,
        tmp_path,
    ):
        """T3: pubsub SSE와 log file tail fallback이 같은 classification/artifact policy를 보존한다."""
        runner_id = "fb-structured-01"
        line = "[12:00:01] [RESULT] exit=1 timeout artifact=.tmp/codex/schema/evidence.json"
        log_file = tmp_path / "runner-structured.log"
        log_file.write_text("boot\n", encoding="utf-8")

        sync_redis.sadd("plan-runner:active_runners", runner_id)
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "AGENTS.md")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path", str(log_file))

        emit_pubsub = True

        async def log_get_message(**kwargs):
            nonlocal emit_pubsub
            if emit_pubsub:
                emit_pubsub = False
                return {
                    "type": "pmessage",
                    "channel": f"plan-runner:logs:{runner_id}",
                    "pattern": LOG_CHANNEL_PATTERN,
                    "data": line,
                }
            return None

        self._install_idle_dual_pubsub(async_redis, log_get_message=log_get_message)
        event_service._async = async_redis
        event_service._file_poll_timeout = 0.0
        event_service._file_poll_interval_sec = 0.0

        gen = event_service.stream_events()
        _ = await gen.__anext__()  # connected
        _ = await gen.__anext__()  # status

        pubsub_event = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        await gen.aclose()

        self._install_idle_dual_pubsub(async_redis)
        event_service._async = async_redis
        event_service._log_tailer.drop_tail_state(runner_id)
        gen = event_service.stream_events()
        _ = await gen.__anext__()  # connected
        _ = await gen.__anext__()  # status
        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
        fallback_events = await _collect_events(gen, 5, timeout=1.2)
        await gen.aclose()

        payloads = [
            json.loads(event.split("data: ")[1].split("\n")[0])
            for event in [pubsub_event, *fallback_events]
            if event.startswith("event: log\n")
        ]
        structured = [
            payload["line"]["structured_event"]
            for payload in payloads
            if isinstance(payload.get("line"), dict)
        ]
        assert len(structured) >= 2
        assert {event["failure"]["classification"] for event in structured} == {"retryable"}
        assert {event["artifact"]["allowed"] for event in structured} == {True}
        assert {event["artifact"]["display_path"] for event in structured} == {".tmp/codex/schema/evidence.json"}

    @pytest.mark.asyncio
    async def test_stream_events_log_completed_cleans_tail_state(
        self,
        event_service,
        async_redis,
        sync_redis,
        tmp_path,
    ):
        """R: log_completed 수신 시 runner tail/dedup 상태가 즉시 정리된다."""
        runner_id = "fb-cleanup-01"
        log_file = tmp_path / "runner-cleanup.log"
        log_file.write_text("", encoding="utf-8")

        sync_redis.sadd("plan-runner:active_runners", runner_id)
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path", str(log_file))

        emit_completed = False

        async def log_get_message(**kwargs):
            nonlocal emit_completed
            if emit_completed:
                emit_completed = False
                return {
                    "type": "pmessage",
                    "channel": f"plan-runner:logs:{runner_id}",
                    "pattern": LOG_CHANNEL_PATTERN,
                    "data": _LOG_COMPLETED_SENTINEL,
                }
            return None

        self._install_idle_dual_pubsub(async_redis, log_get_message=log_get_message)
        event_service._async = async_redis
        event_service._file_poll_timeout = 0.0
        event_service._file_poll_interval_sec = 0.0

        gen = event_service.stream_events()
        _ = await gen.__anext__()  # connected
        _ = await gen.__anext__()  # status

        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write("boot\n")

        _ = await asyncio.wait_for(gen.__anext__(), timeout=2.0)  # fallback log 이벤트
        assert runner_id in event_service._log_tailer._runner_tail_state

        emit_completed = True
        completed_event = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        await gen.aclose()

        assert completed_event.startswith("event: log_completed\n")
        assert runner_id not in event_service._log_tailer._runner_tail_state


# ─── TestMergeLineChannelRouting ──────────────────────────────────────────────

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
        assert data["reason"] == "merge_failed"

    @pytest.mark.asyncio
    async def test_stream_events_merge_completed_reason_passthrough(self, event_service, async_redis):
        """R: __MERGE_COMPLETED::commit_failed__ → merge_log_completed가 raw reason 유지."""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:merge-log:runner10b",
            "pattern": MERGE_LOG_CHANNEL_PATTERN,
            "data": "__MERGE_COMPLETED::commit_failed__",
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
        assert data["runner_id"] == "runner10b"
        assert data["status"] == "failed"
        assert data["reason"] == "commit_failed"

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
        assert data["reason"] == "failed"

    @pytest.mark.asyncio
    async def test_stream_events_log_completed_includes_error(self, event_service, async_redis, sync_redis):
        """R: log_completed payload에 runner error 요약이 포함된다."""
        runner_id = "runner11e"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:error", "Process exited with code 15")
        log_msg = {
            "type": "pmessage",
            "channel": f"plan-runner:logs:{runner_id}",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": "__COMPLETED::error__",
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
        assert data["runner_id"] == runner_id
        assert data["status"] == "failed"
        assert data["reason"] == "error"
        assert data["error"] == "Process exited with code 15"

    @pytest.mark.asyncio
    async def test_stream_events_log_completed_reason_rate_limited_normalized(self, event_service, async_redis):
        """R: __COMPLETED::rate_limited__ → reason=rate_limit 정규화 + failed 상태."""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:runner12",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": "__COMPLETED::rate_limited__",
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
        assert data["runner_id"] == "runner12"
        assert data["status"] == "failed"
        assert data["reason"] == "rate_limit"

    @pytest.mark.asyncio
    async def test_stream_events_log_completed_reason_commit_failed_failed(self, event_service, async_redis):
        """R: __COMPLETED::commit_failed__ → failed 상태 유지."""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:runner12b",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": "__COMPLETED::commit_failed__",
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
        assert data["runner_id"] == "runner12b"
        assert data["status"] == "failed"
        assert data["reason"] == "commit_failed"

    @pytest.mark.asyncio
    async def test_stream_events_log_completed_reason_stopped_success(self, event_service, async_redis):
        """R: __COMPLETED::stopped__ → non-failed 종료로 분류된다."""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:runner12c",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": "__COMPLETED::stopped__",
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
        assert data["runner_id"] == "runner12c"
        assert data["status"] == "success"
        assert data["reason"] == "stopped"

    @pytest.mark.asyncio
    async def test_stream_events_log_completed_reason_passthrough(self, event_service, async_redis):
        """R: __COMPLETED::{reason}__에서 reason이 그대로 전달된다 (정규화 예외 제외)."""
        log_msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:runner13",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": "__COMPLETED::auto_plan_failed__",
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
        assert data["runner_id"] == "runner13"
        assert data["status"] == "failed"
        assert data["reason"] == "auto_plan_failed"

    @pytest.mark.asyncio
    async def test_merge_line_in_log_channel_yields_log_event(self, event_service, async_redis):
        """R: plan-runner:logs:{id}에 [MERGE] 라인 도착 시 event: log 로 전달됨."""
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
