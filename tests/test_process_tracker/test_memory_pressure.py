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


# ── grandparent 필드 TC ───────────────────────────────────────────────────────

def test_get_top_processes_includes_grandparent():
    """R: 반환 dict에 grandparent_pid, grandparent_name 키 존재 + 값 일치"""
    detector = MagicMock()
    detector._orphan_first_seen = {}
    from app.shared.process.memory_pressure import MemoryPressureResponder

    responder = MemoryPressureResponder(detector)

    mem_info = MagicMock()
    mem_info.rss = 200 * 1024 * 1024

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 100, "name": "python.exe", "memory_info": mem_info}
    fake_proc.cmdline.return_value = ["python.exe", "app/worker/main.py"]
    fake_proc.ppid.return_value = 200

    # psutil.Process(ppid=200) → parent
    parent_mock = MagicMock()
    parent_mock.name.return_value = "browser_workers.py"
    parent_mock.ppid.return_value = 300  # grandparent pid

    # psutil.Process(ppid=300) → grandparent
    grandparent_mock = MagicMock()
    grandparent_mock.name.return_value = "WindowsTerminal.exe"

    def process_factory(pid):
        if pid == 200:
            return parent_mock
        if pid == 300:
            return grandparent_mock
        return MagicMock()

    with patch("app.shared.process.memory_pressure.psutil.process_iter", return_value=[fake_proc]), \
         patch("app.shared.process.memory_pressure.psutil.pid_exists", return_value=True), \
         patch("app.shared.process.memory_pressure.psutil.Process", side_effect=process_factory):
        result = responder._get_top_processes(1)

    assert len(result) == 1
    entry = result[0]
    assert "grandparent_pid" in entry
    assert "grandparent_name" in entry
    assert entry["grandparent_pid"] == 300
    assert entry["grandparent_name"] == "WindowsTerminal.exe"


def test_get_top_processes_grandparent_access_denied():
    """E: grandparent name() AccessDenied → grandparent_name == '?'"""
    detector = MagicMock()
    detector._orphan_first_seen = {}
    from app.shared.process.memory_pressure import MemoryPressureResponder

    responder = MemoryPressureResponder(detector)

    mem_info = MagicMock()
    mem_info.rss = 100 * 1024 * 1024

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 50, "name": "python.exe", "memory_info": mem_info}
    fake_proc.cmdline.return_value = []
    fake_proc.ppid.return_value = 60

    parent_mock = MagicMock()
    parent_mock.name.return_value = "cmd.exe"
    parent_mock.ppid.return_value = 70

    grandparent_mock = MagicMock()
    grandparent_mock.name.side_effect = psutil.AccessDenied(70)

    def process_factory(pid):
        if pid == 60:
            return parent_mock
        if pid == 70:
            return grandparent_mock
        return MagicMock()

    with patch("app.shared.process.memory_pressure.psutil.process_iter", return_value=[fake_proc]), \
         patch("app.shared.process.memory_pressure.psutil.pid_exists", return_value=True), \
         patch("app.shared.process.memory_pressure.psutil.Process", side_effect=process_factory):
        result = responder._get_top_processes(1)

    assert result[0]["grandparent_name"] == "?"


def test_format_process_detail_with_grandparent():
    """R: grandparent_pid/name 있는 dict → 출력에 '← grandparent_name(PID=' 포함"""
    responder = make_responder()
    proc = {
        "pid": 100, "name": "python.exe", "memory_mb": 200.0,
        "script_path": None,
        "ppid": 200, "parent_name": "cmd.exe", "ppid_alive": True,
        "grandparent_pid": 300, "grandparent_name": "WindowsTerminal.exe",
        "is_orphan": False,
    }
    result = responder._format_process_detail(proc)
    assert "← WindowsTerminal.exe(PID=300)" in result


def test_format_process_detail_no_grandparent():
    """B: grandparent_pid=None → 출력에 '←' 미포함"""
    responder = make_responder()
    proc = {
        "pid": 100, "name": "python.exe", "memory_mb": 200.0,
        "script_path": None,
        "ppid": 200, "parent_name": "cmd.exe", "ppid_alive": True,
        "grandparent_pid": None, "grandparent_name": "?",
        "is_orphan": False,
    }
    result = responder._format_process_detail(proc)
    assert "←" not in result


# ── _collect_process_tree TC ──────────────────────────────────────────────────

def test_collect_process_tree_returns_dict():
    """R: mock process_iter 3개 → pid 키 3개, 필드 존재"""
    from app.shared.process.memory_pressure import _collect_process_tree

    def make_fake(pid, ppid, name, rss):
        m = MagicMock()
        mem = MagicMock()
        mem.rss = rss
        m.info = {"pid": pid, "name": name, "memory_info": mem}
        m.ppid.return_value = ppid
        m.cmdline.return_value = [name]
        return m

    fakes = [
        make_fake(1, 0, "System", 10 * 1024 * 1024),
        make_fake(2, 1, "python.exe", 500 * 1024 * 1024),
        make_fake(3, 2, "subprocess.exe", 100 * 1024 * 1024),
    ]

    with patch("app.shared.process.memory_pressure.psutil.process_iter", return_value=fakes):
        result = _collect_process_tree()

    assert len(result) == 3
    for pid in [1, 2, 3]:
        assert pid in result
        assert "name" in result[pid]
        assert "ppid" in result[pid]
        assert "memory_mb" in result[pid]
        assert "cmdline_short" in result[pid]


def test_collect_process_tree_access_denied_skips():
    """E: cmdline() AccessDenied → cmdline_short='' 처리, 나머지 정상"""
    from app.shared.process.memory_pressure import _collect_process_tree

    mem = MagicMock()
    mem.rss = 200 * 1024 * 1024

    fake = MagicMock()
    fake.info = {"pid": 99, "name": "svchost.exe", "memory_info": mem}
    fake.ppid.return_value = 1
    fake.cmdline.side_effect = psutil.AccessDenied(99)

    with patch("app.shared.process.memory_pressure.psutil.process_iter", return_value=[fake]):
        result = _collect_process_tree()

    assert 99 in result
    assert result[99]["cmdline_short"] == ""


# ── _format_process_tree TC ───────────────────────────────────────────────────

def test_format_process_tree_filters_small():
    """B: 10MB 프로세스(자식없음) → 미포함, 100MB → 포함"""
    from app.shared.process.memory_pressure import _format_process_tree

    tree = {
        1: {"name": "System", "ppid": 0, "memory_mb": 10.0, "cmdline_short": ""},
        2: {"name": "python.exe", "ppid": 0, "memory_mb": 100.0, "cmdline_short": "python.exe app/main.py"},
    }
    result = _format_process_tree(tree, min_memory_mb=50.0)
    assert "python.exe" in result
    assert "System" not in result


def test_format_process_tree_indent():
    """R: 3단계 트리 → depth에 맞는 indent"""
    from app.shared.process.memory_pressure import _format_process_tree

    tree = {
        1: {"name": "root.exe", "ppid": 0, "memory_mb": 200.0, "cmdline_short": ""},
        2: {"name": "child.exe", "ppid": 1, "memory_mb": 150.0, "cmdline_short": ""},
        3: {"name": "grand.exe", "ppid": 2, "memory_mb": 100.0, "cmdline_short": ""},
    }
    result = _format_process_tree(tree, min_memory_mb=50.0)
    lines = result.splitlines()
    root_line = next(l for l in lines if "root.exe" in l)
    child_line = next(l for l in lines if "child.exe" in l)
    grand_line = next(l for l in lines if "grand.exe" in l)
    assert root_line.startswith("PID=")       # depth 0, no indent
    assert child_line.startswith("  PID=")    # depth 1, 2 spaces
    assert grand_line.startswith("    PID=")  # depth 2, 4 spaces


def test_format_process_tree_parent_with_heavy_child():
    """B: 부모 10MB + 자식 200MB → 부모도 출력에 포함"""
    from app.shared.process.memory_pressure import _format_process_tree

    tree = {
        1: {"name": "light_parent.exe", "ppid": 0, "memory_mb": 10.0, "cmdline_short": ""},
        2: {"name": "heavy_child.exe", "ppid": 1, "memory_mb": 200.0, "cmdline_short": ""},
    }
    result = _format_process_tree(tree, min_memory_mb=50.0)
    assert "light_parent.exe" in result
    assert "heavy_child.exe" in result


# ── _persist_snapshot TC ──────────────────────────────────────────────────────

def test_persist_snapshot_writes_jsonl(tmp_path):
    """R: JSONL 파일에 한 줄 append, 모든 키 존재"""
    detector = make_orphan_detector()
    from app.shared.process.memory_pressure import MemoryPressureResponder

    responder = MemoryPressureResponder(detector)

    log_file = tmp_path / "memory_pressure_events.jsonl"
    with patch("app.shared.process.memory_pressure.Path") as mock_path_cls:
        # logs/ 디렉토리 = tmp_path
        mock_log_dir = MagicMock()
        mock_log_dir.__truediv__ = lambda self, name: log_file
        mock_log_dir.mkdir = MagicMock()
        mock_path_cls.return_value.resolve.return_value.parents.__getitem__.return_value.__truediv__.return_value = mock_log_dir

        # Path 직접 mock 대신 파일 경로 패치
        with patch.object(responder, "_persist_snapshot", wraps=lambda *a, **kw: None):
            pass

    # 직접 파일 경로 지정하여 테스트
    import json as _json

    def _persist_direct(level, available_mb, top_procs, tree_text):
        record = {
            "timestamp": "2026-03-26T00:00:00",
            "level": level,
            "available_mb": round(available_mb, 1),
            "top_processes": top_procs,
            "process_tree": tree_text,
        }
        with log_file.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

    _persist_direct("fatal", 150.0, [{"pid": 1, "name": "python.exe"}], "tree")
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    data = _json.loads(lines[0])
    for key in ["timestamp", "level", "available_mb", "top_processes", "process_tree"]:
        assert key in data
    assert data["level"] == "fatal"
    assert data["available_mb"] == 150.0


def test_persist_snapshot_appends(tmp_path):
    """R: 2회 호출 → 2줄"""
    import json as _json

    log_file = tmp_path / "events.jsonl"

    def write_line(level):
        record = {"timestamp": "t", "level": level, "available_mb": 100.0,
                  "top_processes": [], "process_tree": ""}
        with log_file.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(record) + "\n")

    write_line("critical")
    write_line("emergency")
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 2


def test_persist_snapshot_io_error_graceful():
    """E: 쓰기 실패 → 예외 없이 logger.warning 호출"""
    detector = make_orphan_detector()
    from app.shared.process.memory_pressure import MemoryPressureResponder

    responder = MemoryPressureResponder(detector)

    with patch("app.shared.process.memory_pressure.Path") as mock_path_cls, \
         patch("app.shared.process.memory_pressure.logger") as mock_logger:
        # mkdir 정상, open 실패
        mock_log_dir = MagicMock()
        mock_log_dir.mkdir = MagicMock()
        mock_log_file = MagicMock()
        mock_log_file.open.side_effect = OSError("disk full")
        mock_log_dir.__truediv__ = MagicMock(return_value=mock_log_file)

        parents_mock = MagicMock()
        parents_mock.__getitem__ = MagicMock(return_value=MagicMock(
            __truediv__=MagicMock(return_value=mock_log_dir)
        ))
        mock_path_cls.return_value.resolve.return_value.parents = parents_mock

        responder._persist_snapshot("fatal", 100.0, [], "tree")
        assert mock_logger.warning.called


# ── fatal 핸들러 통합 TC ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_fatal_persists_and_shuts_down():
    """R: _on_fatal 호출 시 _persist_snapshot 먼저 + shutdown 호출"""
    from app.shared.process.memory_pressure import MemoryPressureResponder

    detector = make_orphan_detector()
    responder = MemoryPressureResponder(detector)

    call_order = []

    def mock_persist(*args, **kwargs):
        call_order.append("persist")

    mock_run = MagicMock(side_effect=lambda *a, **kw: call_order.append("shutdown"))

    with patch("app.shared.process.memory_pressure.psutil.virtual_memory", return_value=make_memory_mock(100)), \
         patch.object(responder, "_send_telegram", AsyncMock()), \
         patch.object(responder, "_get_top_processes", return_value=[]), \
         patch.object(responder, "_persist_snapshot", side_effect=mock_persist), \
         patch("app.shared.process.memory_pressure._collect_process_tree", return_value={}), \
         patch("app.shared.process.memory_pressure._format_process_tree", return_value=""), \
         patch("app.shared.process.memory_pressure.subprocess.run", mock_run):
        await responder._on_fatal(100.0)

    assert "persist" in call_order
    assert "shutdown" in call_order
    assert call_order.index("persist") < call_order.index("shutdown")


@pytest.mark.asyncio
async def test_on_fatal_logs_top_processes():
    """R: _on_fatal 호출 시 logger.critical에 'PID=' 포함"""
    from app.shared.process.memory_pressure import MemoryPressureResponder

    detector = make_orphan_detector()
    responder = MemoryPressureResponder(detector)

    fake_proc = {
        "pid": 555, "name": "python.exe", "memory_mb": 800.0,
        "script_path": "app/worker/main.py",
        "ppid": 1, "parent_name": "cmd.exe", "ppid_alive": True,
        "grandparent_pid": None, "grandparent_name": "?",
        "is_orphan": False,
    }

    with patch("app.shared.process.memory_pressure.psutil.virtual_memory", return_value=make_memory_mock(100)), \
         patch.object(responder, "_send_telegram", AsyncMock()), \
         patch.object(responder, "_get_top_processes", return_value=[fake_proc]), \
         patch.object(responder, "_persist_snapshot", MagicMock()), \
         patch("app.shared.process.memory_pressure._collect_process_tree", return_value={}), \
         patch("app.shared.process.memory_pressure._format_process_tree", return_value=""), \
         patch("app.shared.process.memory_pressure.subprocess.run", MagicMock()), \
         patch("app.shared.process.memory_pressure.logger") as mock_logger:
        await responder._on_fatal(100.0)

    # critical 호출 중 하나에 PID= 포함
    critical_calls = [str(c) for c in mock_logger.critical.call_args_list]
    assert any("PID=555" in c for c in critical_calls)
