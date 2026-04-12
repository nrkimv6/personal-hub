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


@pytest.mark.asyncio
async def test_stream_log_file_fallback_entered_flag(tmp_path):
    """I(Inverse): _fallback_entered flag — fallback_mode 이벤트가 2회 폴링에서 정확히 1회만 yield"""
    log_file = tmp_path / "flag.log"
    log_file.write_text("line-x\nline-y\n", encoding="utf-8")

    from app.modules.dev_runner.services.log_service import LogService

    svc = MagicMock(spec=LogService)
    svc.async_redis = AsyncMock()
    svc.async_redis.ping = AsyncMock()

    # 3번 None (파일 폴링 2회) 후 __COMPLETED__ 종료
    _cc = [0]
    async def get_message_side_effect(**kwargs):
        _cc[0] += 1
        if _cc[0] >= 4:
            return {"type": "message", "data": "__COMPLETED__"}
        return None

    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = get_message_side_effect
    mock_pubsub.subscribe = AsyncMock()
    svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)
    svc._find_current_log = MagicMock(return_value=log_file)

    _ticks = [0]

    def fake_monotonic():
        _ticks[0] += 1
        if _ticks[0] <= 2:
            return 1000.0
        return 1010.0  # 10초 경과 → fallback 진입

    collected = []
    with patch("app.modules.dev_runner.services.log_service.time") as mock_time:
        mock_time.monotonic = fake_monotonic
        async for chunk in LogService.stream_log_file(svc, "flag-runner"):
            collected.append(chunk)

    # fallback_mode 이벤트가 정확히 1회만 yield되어야 함
    fallback_events = [c for c in collected if "event: fallback_mode" in c]
    assert len(fallback_events) == 1, (
        f"fallback_mode 이벤트가 {len(fallback_events)}회 yield됨 (기대: 1회)\n"
        f"_fallback_entered flag 미동작: {collected}"
    )


@pytest.mark.asyncio
async def test_stream_log_file_fallback_multiline_frame_single_sse_event(tmp_path):
    """파일 폴링 fallback이 멀티라인 RESULT를 단일 SSE 이벤트로 보낸다."""
    log_file = tmp_path / "framed.log"
    log_file.write_text(
        "[12:00:00] [RESULT] line-1\nline-2\nline-3\n[12:00:01] [AI] done\n",
        encoding="utf-8",
    )

    from app.modules.dev_runner.services.log_service import LogService

    svc = MagicMock(spec=LogService)
    svc.async_redis = AsyncMock()
    svc.async_redis.ping = AsyncMock()

    calls = [0]

    async def get_message_side_effect(**kwargs):
        calls[0] += 1
        if calls[0] >= 3:
            return {"type": "message", "data": "__COMPLETED__"}
        return None

    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = get_message_side_effect
    mock_pubsub.subscribe = AsyncMock()
    svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)
    svc._find_current_log = MagicMock(return_value=log_file)

    ticks = [0]

    def fake_monotonic():
        ticks[0] += 1
        if ticks[0] <= 2:
            return 1000.0
        return 1010.0

    collected = []
    with patch("app.modules.dev_runner.services.log_service.time") as mock_time:
        mock_time.monotonic = fake_monotonic
        async for chunk in LogService.stream_log_file(svc, "framed-runner"):
            collected.append(chunk)

    result_chunks = [c for c in collected if "[RESULT] line-1" in c]
    assert len(result_chunks) == 1, f"RESULT가 분절됨: {collected}"
    assert "data: line-2" in result_chunks[0]
    assert "data: line-3" in result_chunks[0]


# ---------------------------------------------------------------------------
# T3: 근본 원인 재현 TC — 실제 파일시스템 + pubsub None 시나리오
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_seek_end_regression(tmp_path):
    """T3(재현): pubsub None 시 fallback 진입 후 기존 파일 내용이 클라이언트에 전달되는지.

    버그 재현 조건:
    - since_line=0 (기본값)
    - pubsub이 첫 메시지 수신 전에 5초 타임아웃
    - 로그 파일에 기존 내용이 존재

    수정 전 동작 (버그): EOF seek으로 _file_pos=파일끝 → 기존 내용 전달 안 됨
    수정 후 동작 (정상): _file_pos=0 유지 → 파일 처음부터 읽어 기존 내용 전달됨

    mock: Redis pubsub만 사용, 파일시스템은 실물 (tmp_path).
    """
    log_file = tmp_path / "regression.log"
    log_file.write_text(
        "regression-line-1\nregression-line-2\nregression-line-3\n",
        encoding="utf-8",
    )

    from app.modules.dev_runner.services.log_service import LogService

    svc = MagicMock(spec=LogService)
    svc.async_redis = AsyncMock()
    svc.async_redis.ping = AsyncMock()

    # pubsub은 아무 메시지도 전달하지 않다가 __COMPLETED__ 반환
    _step = [0]
    async def pubsub_none_then_complete(**kwargs):
        _step[0] += 1
        if _step[0] >= 3:
            return {"type": "message", "data": "__COMPLETED__"}
        return None  # pubsub 메시지 없음 → fallback 유발

    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = pubsub_none_then_complete
    mock_pubsub.subscribe = AsyncMock()
    svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)
    # _find_current_log는 실제 tmp_path 파일 반환 (파일시스템 실물)
    svc._find_current_log = MagicMock(return_value=log_file)

    _tick = [0]

    def fake_monotonic():
        _tick[0] += 1
        if _tick[0] <= 2:
            return 1000.0  # 초기화 시점
        return 1010.0  # 10초 경과 → FILE_POLL_TIMEOUT 초과

    collected = []
    with patch("app.modules.dev_runner.services.log_service.time") as mock_time:
        mock_time.monotonic = fake_monotonic
        async for chunk in LogService.stream_log_file(svc, "regression-runner"):
            collected.append(chunk)

    data_chunks = [c for c in collected if c.startswith("data:")]
    combined = " ".join(data_chunks)

    # 수정 전 버그 재현 확인: 기존 파일 내용이 전달되어야 함
    assert "regression-line-1" in combined, (
        f"regression-line-1 누락 — EOF seek 버그 재발 가능성\n"
        f"collected={collected}"
    )
    assert "regression-line-2" in combined, (
        f"regression-line-2 누락 — EOF seek 버그 재발 가능성\n"
        f"collected={collected}"
    )
    assert "regression-line-3" in combined, (
        f"regression-line-3 누락 — EOF seek 버그 재발 가능성\n"
        f"collected={collected}"
    )
