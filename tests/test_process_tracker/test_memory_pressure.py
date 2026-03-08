"""MemoryPressureResponder TC"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_memory_mock(available_mb: float):
    """psutil.virtual_memory() mock 생성."""
    mem = MagicMock()
    mem.available = int(available_mb * 1024 * 1024)
    return mem


def make_orphan_detector():
    detector = MagicMock()
    detector.scan = AsyncMock(return_value=[])
    detector.cleanup = AsyncMock(return_value=[])
    return detector


@pytest.mark.asyncio
async def test_check_normal_above_4gb():
    """R: available=5GB → 'normal', 알림 없음"""
    from app.shared.process.memory_pressure import MemoryPressureResponder

    detector = make_orphan_detector()
    responder = MemoryPressureResponder(detector)

    with patch("app.shared.process.memory_pressure.psutil.virtual_memory", return_value=make_memory_mock(5000)):
        level = await responder.check()

    assert level == "normal"


@pytest.mark.asyncio
async def test_check_caution_below_4gb():
    """R: available=3GB → 'caution', send_telegram 호출 확인"""
    from app.shared.process.memory_pressure import MemoryPressureResponder

    detector = make_orphan_detector()
    responder = MemoryPressureResponder(detector)

    mock_telegram = AsyncMock()

    with patch("app.shared.process.memory_pressure.psutil.virtual_memory", return_value=make_memory_mock(3000)), \
         patch.object(responder, "_send_telegram", mock_telegram), \
         patch.object(responder, "_get_top_processes", return_value=[]):
        level = await responder.check()

    assert level == "caution"
    mock_telegram.assert_called_once()


@pytest.mark.asyncio
async def test_check_fatal_below_256mb():
    """R: available=200MB → 'fatal', subprocess.run(["shutdown",...]) 호출 확인"""
    from app.shared.process.memory_pressure import MemoryPressureResponder

    detector = make_orphan_detector()
    responder = MemoryPressureResponder(detector)

    mock_telegram = AsyncMock()
    mock_run = MagicMock()

    with patch("app.shared.process.memory_pressure.psutil.virtual_memory", return_value=make_memory_mock(200)), \
         patch.object(responder, "_send_telegram", mock_telegram), \
         patch("app.shared.process.memory_pressure.subprocess.run", mock_run):
        level = await responder.check()

    assert level == "fatal"
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "shutdown" in call_args


@pytest.mark.asyncio
async def test_alert_cooldown_suppresses_duplicate():
    """B: caution 2회 연속 (10분 미경과) → 2번째 send_telegram 미호출"""
    from app.shared.process.memory_pressure import MemoryPressureResponder

    detector = make_orphan_detector()
    responder = MemoryPressureResponder(detector)

    mock_telegram = AsyncMock()

    with patch("app.shared.process.memory_pressure.psutil.virtual_memory", return_value=make_memory_mock(3000)), \
         patch.object(responder, "_send_telegram", mock_telegram), \
         patch.object(responder, "_get_top_processes", return_value=[]):
        await responder.check()  # 1회
        await responder.check()  # 2회 (쿨다운)

    # 1회만 호출됨
    assert mock_telegram.call_count == 1


@pytest.mark.asyncio
async def test_fatal_triggered_once_only():
    """B: fatal 2회 → 2번째 shutdown 미호출"""
    from app.shared.process.memory_pressure import MemoryPressureResponder

    detector = make_orphan_detector()
    responder = MemoryPressureResponder(detector)

    mock_telegram = AsyncMock()
    mock_run = MagicMock()

    with patch("app.shared.process.memory_pressure.psutil.virtual_memory", return_value=make_memory_mock(100)), \
         patch.object(responder, "_send_telegram", mock_telegram), \
         patch("app.shared.process.memory_pressure.subprocess.run", mock_run):
        await responder.check()  # 1회 → fatal
        await responder.check()  # 2회 → _fatal_triggered=True → 스킵

    assert mock_run.call_count == 1
