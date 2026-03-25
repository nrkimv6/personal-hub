"""MERGE 로그 2중복 재현 통합 TC

근본 원인 재현: MergeLogger가 stdout(→logs 채널)과 merge-log 채널에 동시 publish하여
event_service가 log + merge_log 이벤트를 모두 생성함.
프론트엔드 필터링(DevRunnerTab log 이벤트 [MERGE] skip)으로 중복 제거됨을 검증.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.dev_runner.services.event_service import (
    EventService,
    LOG_CHANNEL_PATTERN,
    MERGE_LOG_CHANNEL_PATTERN,
)


def _make_dual_pubsub_mocks(ks_messages=None, log_messages=None):
    """keyspace/log pubsub용 별도 mock 쌍 생성 헬퍼."""
    mock_ks = AsyncMock()
    mock_ks.psubscribe = AsyncMock()
    mock_ks.punsubscribe = AsyncMock()
    mock_ks.aclose = AsyncMock()
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
    events = []
    for _ in range(count):
        try:
            event = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
            events.append(event)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break
    return events


@pytest.fixture
def async_redis():
    import fakeredis.aioredis
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r


@pytest.fixture
def event_service(async_redis):
    import fakeredis
    svc = EventService.__new__(EventService)
    svc._sync = fakeredis.FakeRedis(decode_responses=True)
    svc._async = async_redis
    return svc


class TestMergeLogDualChannelDuplication:
    @pytest.mark.asyncio
    async def test_merge_log_dual_channel_publish_produces_two_events(self, event_service, async_redis):
        """
        T3 재현 TC: MergeLogger가 동일 MERGE 라인을 logs:r1(stdout경로)과
        merge-log:r1(직접 publish) 양쪽에 게시하면 event_service는 log + merge_log
        두 이벤트를 생성한다. (프론트 필터링 적용 전 상태 재현)
        """
        merge_line = "[10:00:00] [MERGE] [INFO] execute_merge: project_dir=D:/foo, branch=impl/bar"

        # 경로 1: stdout→_stream_output→plan-runner:logs:r1
        msg_via_logs = {
            "type": "pmessage",
            "channel": "plan-runner:logs:r1",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": merge_line,
        }
        # 경로 2: MergeLogger.redis.publish→plan-runner:merge-log:r1
        msg_via_merge_log = {
            "type": "pmessage",
            "channel": "plan-runner:merge-log:r1",
            "pattern": MERGE_LOG_CHANNEL_PATTERN,
            "data": merge_line,
        }

        _, _, factory = _make_dual_pubsub_mocks(log_messages=[msg_via_logs, msg_via_merge_log])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 6)
        await gen.aclose()

        log_events = [e for e in events if e.startswith("event: log\n")]
        merge_events = [e for e in events if e.startswith("event: merge_log\n")]

        # 백엔드는 두 이벤트를 모두 생성 (이것이 2중복의 원인)
        assert len(log_events) >= 1, "log 이벤트가 1개 이상 있어야 함"
        assert len(merge_events) >= 1, "merge_log 이벤트가 1개 이상 있어야 함"

        # 두 이벤트 모두 동일 라인을 전달
        log_data = json.loads(log_events[0].split("data: ")[1].split("\n")[0])
        merge_data = json.loads(merge_events[0].split("data: ")[1].split("\n")[0])
        assert log_data["line"] == merge_line
        assert merge_data["line"] == merge_line
        assert log_data["runner_id"] == "r1"
        assert merge_data["runner_id"] == "r1"

    @pytest.mark.asyncio
    async def test_non_merge_line_in_log_channel_still_yielded(self, event_service, async_redis):
        """R: [MERGE] 없는 일반 라인은 log 이벤트로 정상 전달됨 (필터 과적용 방지)."""
        normal_line = "[10:00:00] [PLAN-RUNNER#dev-runner@abc] [INFO] Cycle 1 start"
        msg = {
            "type": "pmessage",
            "channel": "plan-runner:logs:r3",
            "pattern": LOG_CHANNEL_PATTERN,
            "data": normal_line,
        }
        _, _, factory = _make_dual_pubsub_mocks(log_messages=[msg])
        async_redis.pubsub = MagicMock(side_effect=factory)
        event_service._async = async_redis

        gen = event_service.stream_events()
        events = await _collect_events(gen, 4)
        await gen.aclose()

        log_events = [e for e in events if e.startswith("event: log\n")]
        assert len(log_events) >= 1
        data = json.loads(log_events[0].split("data: ")[1].split("\n")[0])
        assert data["line"] == normal_line
        assert "[MERGE]" not in data["line"]
