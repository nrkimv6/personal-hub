"""log_service sentinel 파싱 TC

__MERGE_COMPLETED__:SUCCESS / :FAILED / (접미사 없음) 및 __COMPLETED__:FAILED 파싱 검증.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.dev_runner.services.log_service import LogService


def _make_pubsub_mock(messages: list) -> MagicMock:
    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()
    mock_pubsub.get_message = AsyncMock(side_effect=messages + [None] * 200)
    return mock_pubsub


def _make_log_service(messages: list) -> LogService:
    """주어진 메시지 목록을 반환하는 mock pubsub으로 LogService 인스턴스 생성."""
    svc = LogService.__new__(LogService)
    mock_pubsub = _make_pubsub_mock(messages)
    mock_async_redis = MagicMock()
    mock_async_redis.ping = AsyncMock(return_value=True)
    mock_async_redis.pubsub = MagicMock(return_value=mock_pubsub)
    svc.async_redis = mock_async_redis
    return svc


def _msg(data: str) -> dict:
    return {"type": "message", "data": data}


async def _collect(gen, max_items: int = 10, timeout: float = 2.0) -> list[str]:
    items = []
    for _ in range(max_items):
        try:
            chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
            items.append(chunk)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break
    return items


class TestMergeCompletedSentinelParsing:
    """stream_merge_log: __MERGE_COMPLETED__ sentinel 파싱 TC"""

    @pytest.mark.asyncio
    async def test_merge_completed_success_sse(self):
        """R: __MERGE_COMPLETED__:SUCCESS → event: completed / data: completed"""
        svc = _make_log_service([_msg("__MERGE_COMPLETED__:SUCCESS")])
        chunks = await _collect(svc.stream_merge_log("r1"))

        completed = [c for c in chunks if "event: completed" in c]
        assert len(completed) == 1, f"completed 이벤트가 1개여야 함, got: {chunks}"
        assert "data: completed" in completed[0], f"data: completed 기대, got: {completed[0]}"

    @pytest.mark.asyncio
    async def test_merge_completed_failed_sse(self):
        """R: __MERGE_COMPLETED__:FAILED → event: completed / data: merge_failed"""
        svc = _make_log_service([_msg("__MERGE_COMPLETED__:FAILED")])
        chunks = await _collect(svc.stream_merge_log("r1"))

        completed = [c for c in chunks if "event: completed" in c]
        assert len(completed) == 1, f"completed 이벤트가 1개여야 함, got: {chunks}"
        assert "data: merge_failed" in completed[0], f"data: merge_failed 기대, got: {completed[0]}"

    @pytest.mark.asyncio
    async def test_merge_completed_no_suffix_backward_compat(self):
        """B: __MERGE_COMPLETED__ (접미사 없음) → data: completed (하위호환 기본값)"""
        svc = _make_log_service([_msg("__MERGE_COMPLETED__")])
        chunks = await _collect(svc.stream_merge_log("r1"))

        completed = [c for c in chunks if "event: completed" in c]
        assert len(completed) == 1
        assert "data: completed" in completed[0], f"하위호환 기본값 completed 기대, got: {completed[0]}"

    @pytest.mark.asyncio
    async def test_log_completed_failed_sse(self):
        """R: __COMPLETED::failed__ → stream_log_file completed 이벤트에 reason: failed

        포맷: __COMPLETED::{reason}__ (언더스코어 2개는 접두사/접미사, COMPLETED 뒤에 __)
        """
        svc = _make_log_service([_msg("__COMPLETED::failed__")])
        chunks = await _collect(svc.stream_log_file("r1"))

        completed = [c for c in chunks if "event: completed" in c]
        assert len(completed) == 1, f"completed 이벤트가 1개여야 함, got: {chunks}"
        assert "data: failed" in completed[0], f"reason=failed 기대, got: {completed[0]}"

    @pytest.mark.asyncio
    async def test_log_completed_commit_failed_sse(self):
        """R: __COMPLETED::commit_failed__ → stream_log_file completed 이벤트에 reason: commit_failed"""
        svc = _make_log_service([_msg("__COMPLETED::commit_failed__")])
        chunks = await _collect(svc.stream_log_file("r1"))

        completed = [c for c in chunks if "event: completed" in c]
        assert len(completed) == 1, f"completed 이벤트가 1개여야 함, got: {chunks}"
        assert "data: commit_failed" in completed[0], f"reason=commit_failed 기대, got: {completed[0]}"
