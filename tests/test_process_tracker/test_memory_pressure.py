"""MemoryPressureResponder TC"""
import time
import pytest
import psutil
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
    detector._orphan_first_seen = {}
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
    """R: available=3GB → 'caution', Telegram 알림 없음 (caution은 로그만)"""
    from app.shared.process.memory_pressure import MemoryPressureResponder

    detector = make_orphan_detector()
    responder = MemoryPressureResponder(detector)

    mock_telegram = AsyncMock()

    with patch("app.shared.process.memory_pressure.psutil.virtual_memory", return_value=make_memory_mock(3000)), \
         patch.object(responder, "_send_telegram", mock_telegram), \
         patch.object(responder, "_get_top_processes", return_value=[]):
        level = await responder.check()

    assert level == "caution"
    mock_telegram.assert_not_called()  # caution 단계는 Telegram 알림 없음


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
    """B: critical 2회 연속 (10분 미경과) → 2번째 send_telegram 미호출"""
    from app.shared.process.memory_pressure import MemoryPressureResponder

    detector = make_orphan_detector()
    detector._orphan_first_seen = {}
    responder = MemoryPressureResponder(detector)

    mock_telegram = AsyncMock()

    with patch("app.shared.process.memory_pressure.psutil.virtual_memory", return_value=make_memory_mock(700)), \
         patch.object(responder, "_send_telegram", mock_telegram), \
         patch.object(responder, "_get_top_processes", return_value=[]):
        await responder.check()  # 1회 → critical, Telegram 발송
        await responder.check()  # 2회 → 쿨다운, 미발송

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


# ── _extract_script_path ──────────────────────────────────────────────────────

def test_extract_script_path_python():
    """R: python + .py 인자 → 경로 반환"""
    from app.shared.process.memory_pressure import _extract_script_path
    result = _extract_script_path(["python", "app/worker/orchestrator.py", "--flag"])
    assert result == "app/worker/orchestrator.py"


def test_extract_script_path_powershell():
    """R: powershell + .ps1 인자 → 경로 반환"""
    from app.shared.process.memory_pressure import _extract_script_path
    result = _extract_script_path(["powershell.exe", "-File", "scripts/run.ps1"])
    assert result == "scripts/run.ps1"


def test_extract_script_path_cmd():
    """R: cmd + .bat 인자 → 경로 반환"""
    from app.shared.process.memory_pressure import _extract_script_path
    result = _extract_script_path(["cmd.exe", "/c", "scripts/setup.bat"])
    assert result == "scripts/setup.bat"


def test_extract_script_path_none():
    """B: 스크립트 없는 일반 프로세스 → None"""
    from app.shared.process.memory_pressure import _extract_script_path
    result = _extract_script_path(["chrome.exe", "--no-sandbox"])
    assert result is None


def test_extract_script_path_empty():
    """B: 빈 cmdline → None"""
    from app.shared.process.memory_pressure import _extract_script_path
    result = _extract_script_path([])
    assert result is None


# ── _shorten_path ─────────────────────────────────────────────────────────────

def test_shorten_path_short():
    """B: 80자 미만 → 그대로 반환"""
    from app.shared.process.memory_pressure import _shorten_path
    short = "app/worker/orchestrator.py"
    assert _shorten_path(short) == short


def test_shorten_path_long():
    """R: 80자 초과 → …\\parent\\filename 형태"""
    from app.shared.process.memory_pressure import _shorten_path
    long_path = "D:/very/long/nested/directory/structure/that/exceeds/eighty/characters/orchestrator.py"
    result = _shorten_path(long_path)
    assert result.startswith("…")
    assert "orchestrator.py" in result
    assert len(result) < len(long_path)


# ── _format_process_detail ────────────────────────────────────────────────────

def make_responder():
    detector = MagicMock()
    detector._orphan_first_seen = {}
    from app.shared.process.memory_pressure import MemoryPressureResponder
    return MemoryPressureResponder(detector)


def test_format_process_detail_with_script():
    """R: script_path 있을 때 → [경로] 포함"""
    responder = make_responder()
    proc = {
        "pid": 1234, "name": "python.exe", "memory_mb": 512.0,
        "script_path": "app/worker/orchestrator.py",
        "ppid": 5678, "parent_name": "browser_workers.py",
        "ppid_alive": True, "is_orphan": False,
    }
    result = responder._format_process_detail(proc)
    assert "[app/worker/orchestrator.py]" in result
    assert "PID=1234" in result


def test_format_process_detail_without_script():
    """R: script_path=None → [ 미포함"""
    responder = make_responder()
    proc = {
        "pid": 9999, "name": "chrome.exe", "memory_mb": 300.0,
        "script_path": None,
        "ppid": 1, "parent_name": "explorer.exe",
        "ppid_alive": True, "is_orphan": False,
    }
    result = responder._format_process_detail(proc)
    assert "[" not in result
    assert "chrome.exe" in result


def test_format_process_detail_orphan_yes():
    """R: is_orphan=True → 'orphan: YES' 포함"""
    responder = make_responder()
    proc = {
        "pid": 111, "name": "python.exe", "memory_mb": 100.0,
        "script_path": None,
        "ppid": 999, "parent_name": "?",
        "ppid_alive": False, "is_orphan": True,
    }
    result = responder._format_process_detail(proc)
    assert "orphan: YES" in result


def test_format_process_detail_orphan_no():
    """B: is_orphan=False → 'orphan: NO' 포함"""
    responder = make_responder()
    proc = {
        "pid": 222, "name": "python.exe", "memory_mb": 200.0,
        "script_path": None,
        "ppid": 1, "parent_name": "explorer.exe",
        "ppid_alive": True, "is_orphan": False,
    }
    result = responder._format_process_detail(proc)
    assert "orphan: NO" in result


# ── _get_top_processes 확장 ───────────────────────────────────────────────────

def test_get_top_processes_includes_extended_fields():
    """R: 반환 dict에 확장 필드 포함 확인"""
    detector = MagicMock()
    detector._orphan_first_seen = {}
    from app.shared.process.memory_pressure import MemoryPressureResponder

    responder = MemoryPressureResponder(detector)

    mem_info = MagicMock()
    mem_info.rss = 512 * 1024 * 1024  # 512MB

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 1234, "name": "python.exe", "memory_info": mem_info}
    fake_proc.cmdline.return_value = ["python.exe", "app/worker/orchestrator.py"]
    fake_proc.ppid.return_value = 5678

    parent_proc = MagicMock()
    parent_proc.name.return_value = "browser_workers.py"

    with patch("app.shared.process.memory_pressure.psutil.process_iter", return_value=[fake_proc]), \
         patch("app.shared.process.memory_pressure.psutil.pid_exists", return_value=True), \
         patch("app.shared.process.memory_pressure.psutil.Process", return_value=parent_proc):
        result = responder._get_top_processes(1)

    assert len(result) == 1
    entry = result[0]
    assert "script_path" in entry
    assert "ppid" in entry
    assert "parent_name" in entry
    assert "ppid_alive" in entry
    assert "is_orphan" in entry
    assert entry["script_path"] == "app/worker/orchestrator.py"


def test_get_top_processes_access_denied_graceful():
    """E: cmdline() AccessDenied → script_path=None으로 정상 반환"""
    detector = MagicMock()
    detector._orphan_first_seen = {}
    from app.shared.process.memory_pressure import MemoryPressureResponder

    responder = MemoryPressureResponder(detector)

    mem_info = MagicMock()
    mem_info.rss = 100 * 1024 * 1024

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 9999, "name": "svchost.exe", "memory_info": mem_info}
    fake_proc.cmdline.side_effect = psutil.AccessDenied(9999)
    fake_proc.ppid.return_value = 1

    parent_proc = MagicMock()
    parent_proc.name.return_value = "services.exe"

    with patch("app.shared.process.memory_pressure.psutil.process_iter", return_value=[fake_proc]), \
         patch("app.shared.process.memory_pressure.psutil.pid_exists", return_value=True), \
         patch("app.shared.process.memory_pressure.psutil.Process", return_value=parent_proc):
        result = responder._get_top_processes(1)

    assert len(result) == 1
    assert result[0]["script_path"] is None


# ── warning 로그 출력 ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_warning_logs_process_detail():
    """R: _on_warning 호출 시 로그에 PID= 패턴 포함"""
    from app.shared.process.memory_pressure import MemoryPressureResponder

    detector = MagicMock()
    detector._orphan_first_seen = {}
    detector.scan = AsyncMock(return_value=[])
    detector.cleanup = AsyncMock(return_value=[])
    responder = MemoryPressureResponder(detector)

    fake_proc = {
        "pid": 1234, "name": "python.exe", "memory_mb": 512.0,
        "script_path": "app/worker/orchestrator.py",
        "ppid": 5678, "parent_name": "browser_workers.py",
        "ppid_alive": True, "is_orphan": False,
    }

    with patch.object(responder, "_get_top_processes", return_value=[fake_proc]):
        import logging
        with patch("app.shared.process.memory_pressure.logger") as mock_logger:
            await responder._on_warning(1500.0)
            assert mock_logger.warning.called
            log_msg = mock_logger.warning.call_args[0][0]
            assert "PID=1234" in log_msg
            assert "app/worker/orchestrator.py" in log_msg
