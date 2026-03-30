"""log_service.stream_log_file() 파일 폴링 fallback TC"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# T1-12: pub/sub 5초 미수신 시 파일 폴링 전환 (BOUNDARY)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_log_file_fallback_to_file(tmp_path):
    """B(Boundary): pub/sub 5초 미수신 → 파일 폴링으로 내용 전달 후 __COMPLETED__ 종료"""
    log_file = tmp_path / "test.log"
    log_file.write_text("line-a\nline-b\nline-c\n", encoding="utf-8")

    from app.modules.dev_runner.services.log_service import LogService

    svc = MagicMock(spec=LogService)
    svc.async_redis = AsyncMock()
    svc.async_redis.ping = AsyncMock()

    # 첫 몇 번은 None → 파일 폴링 → 이후 __COMPLETED__ 로 종료
    _msg_cc = [0]
    async def get_message_side_effect(**kwargs):
        _msg_cc[0] += 1
        if _msg_cc[0] >= 3:
            return {"type": "message", "data": "__COMPLETED__"}
        return None

    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = get_message_side_effect
    mock_pubsub.subscribe = AsyncMock()
    svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)
    svc._find_current_log = MagicMock(return_value=log_file)

    _base = 1000.0
    _time_cc = [0]

    def fake_monotonic():
        _time_cc[0] += 1
        if _time_cc[0] <= 2:
            return _base  # last_heartbeat, _no_msg_since 초기화: 1000.0
        return _base + 10.0  # 이후 now: 1010.0 → 10초 경과

    collected = []
    with patch("app.modules.dev_runner.services.log_service.time") as mock_time:
        mock_time.monotonic = fake_monotonic
        async for chunk in LogService.stream_log_file(svc, "test-runner"):
            collected.append(chunk)

    data_lines = [c for c in collected if c.startswith("data:")]
    combined = "".join(data_lines)
    assert "line-a" in combined
    assert "line-b" in combined
    assert "line-c" in combined
    # _find_current_log가 호출됐는지 확인
    svc._find_current_log.assert_called()


# ---------------------------------------------------------------------------
# T1-13: pub/sub 메시지 수신 시 파일 폴링 타이머 리셋 (INVERSE)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_log_file_pubsub_resets_timer():
    """I(Inverse): pub/sub 메시지 수신 → 파일 폴링 미진입 후 __COMPLETED__ 종료"""
    from app.modules.dev_runner.services.log_service import LogService

    svc = MagicMock(spec=LogService)
    svc.async_redis = AsyncMock()
    svc.async_redis.ping = AsyncMock()

    _msgs = [
        {"type": "message", "data": "log-line-1"},
        {"type": "message", "data": "log-line-2"},
        {"type": "message", "data": "__COMPLETED__"},
    ]
    _idx = [0]

    async def get_message_side_effect(**kwargs):
        if _idx[0] < len(_msgs):
            m = _msgs[_idx[0]]
            _idx[0] += 1
            return m
        return {"type": "message", "data": "__COMPLETED__"}

    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = get_message_side_effect
    mock_pubsub.subscribe = AsyncMock()
    svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)
    svc._find_current_log = MagicMock(return_value=None)

    _base = 1000.0
    _tick = [0]

    def fake_monotonic():
        _tick[0] += 1
        # 메시지 수신 시마다 _no_msg_since 리셋 시뮬레이션: 0.1초씩만 증가
        return _base + _tick[0] * 0.1

    collected = []
    with patch("app.modules.dev_runner.services.log_service.time") as mock_time:
        mock_time.monotonic = fake_monotonic
        async for chunk in LogService.stream_log_file(svc, "test-runner2"):
            collected.append(chunk)

    data_lines = [c for c in collected if c.startswith("data:")]
    combined = "".join(data_lines)
    assert "log-line-1" in combined
    assert "log-line-2" in combined
    # 파일 폴링은 진입하지 않아야 함 (5초 미만)
    svc._find_current_log.assert_not_called()


# ---------------------------------------------------------------------------
# T1-14: 파일 폴링 후 _file_pos 갱신으로 중복 방지 (CROSS-CHECK)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_log_file_fallback_dedup(tmp_path):
    """X(Cross-check): 파일 폴링 2회에서 _file_pos 갱신으로 중복 없음"""
    log_file = tmp_path / "dedup.log"
    log_file.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")

    from app.modules.dev_runner.services.log_service import LogService

    svc = MagicMock(spec=LogService)
    svc.async_redis = AsyncMock()
    svc.async_redis.ping = AsyncMock()

    # 2번 None (파일 폴링) 후 종료
    _call_count = [0]
    async def get_message_side_effect(**kwargs):
        _call_count[0] += 1
        if _call_count[0] >= 3:
            return {"type": "message", "data": "__COMPLETED__"}
        return None

    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = get_message_side_effect
    mock_pubsub.subscribe = AsyncMock()
    svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)
    svc._find_current_log = MagicMock(return_value=log_file)

    _fc2 = [0]

    def fake_monotonic():
        _fc2[0] += 1
        if _fc2[0] <= 2:
            return 1000.0  # 초기화
        return 1010.0  # 10초 경과

    collected_data = []
    with patch("app.modules.dev_runner.services.log_service.time") as mock_time:
        mock_time.monotonic = fake_monotonic
        async for chunk in LogService.stream_log_file(svc, "test-runner3"):
            if chunk.startswith("data:"):
                collected_data.append(chunk)

    all_content = " ".join(collected_data)
    assert "line-1" in all_content
    assert "line-2" in all_content
    assert "line-3" in all_content

    # 중복 방지: line-1이 정확히 1번만 나타나야 함 (_file_pos 이후만 재읽기)
    line1_count = sum(1 for c in collected_data if "line-1" in c)
    assert line1_count == 1, f"line-1이 {line1_count}번 나왔습니다 (중복 발생)"
