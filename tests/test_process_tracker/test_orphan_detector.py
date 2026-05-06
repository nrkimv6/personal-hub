"""OrphanDetector TC"""
import asyncio
import logging
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_registry(procs: dict):
    """Mock ProcessRegistry."""
    registry = MagicMock()
    registry.get_all = AsyncMock(return_value=procs)
    registry.unregister = AsyncMock(return_value=True)
    return registry


def make_entry(pid: int, ppid: int, name: str = "worker") -> dict:
    return {
        "pid": str(pid),
        "ppid": str(ppid),
        "name": name,
        "exe": "python.exe",
        "role": "worker",
    }


class FakeMem:
    def __init__(self, rss: int = 10 * 1024 * 1024):
        self.rss = rss


class FakeProc:
    def __init__(
        self,
        pid: int,
        name: str = "python.exe",
        ppid: int = 9999,
        cmdline: list[str] | None = None,
        *,
        children: list["FakeProc"] | None = None,
        parent: "FakeProc | None" = None,
        name_error: Exception | None = None,
        cmdline_error: Exception | None = None,
    ):
        self.pid = pid
        self.info = {"pid": pid, "name": name, "ppid": ppid}
        self._name = name
        self._cmdline = cmdline if cmdline is not None else ["python", "-m", "pytest"]
        self._children = children or []
        self._parent = parent
        self._name_error = name_error
        self._cmdline_error = cmdline_error

    def name(self):
        if self._name_error is not None:
            raise self._name_error
        return self._name

    def cmdline(self):
        if self._cmdline_error is not None:
            raise self._cmdline_error
        return self._cmdline

    def memory_info(self):
        return FakeMem()

    def children(self, recursive: bool = False):
        return self._children

    def parent(self):
        return self._parent


class InfoAccessDeniedProc:
    @property
    def info(self):
        raise pytest.importorskip("psutil").AccessDenied(pid=777)


def access_denied(pid: int = 1):
    import psutil

    return psutil.AccessDenied(pid=pid)


def no_such_process(pid: int = 1):
    import psutil

    return psutil.NoSuchProcess(pid=pid)


def make_detector(registry_procs: dict | None = None, grace_period: int = 30):
    from app.shared.process.orphan_detector import OrphanDetector

    return OrphanDetector(make_registry(registry_procs or {}), grace_period=grace_period)


def test__is_safe_process_right_safe_name():
    from app.shared.process.orphan_detector import OrphanDetector

    assert OrphanDetector._is_safe_process(FakeProc(1, name="nssm")) is True


def test__is_safe_process_right_monitorpage_prefix():
    from app.shared.process.orphan_detector import OrphanDetector

    assert OrphanDetector._is_safe_process(FakeProc(1, name="monitorpage-worker")) is True


def test__is_safe_process_right_safe_cmdline():
    from app.shared.process.orphan_detector import OrphanDetector

    proc = FakeProc(1, cmdline=["python", "app.worker.main"])

    assert OrphanDetector._is_safe_process(proc) is True


def test__is_safe_process_right_unsafe_pytest():
    from app.shared.process.orphan_detector import OrphanDetector

    proc = FakeProc(1, name="python.exe", cmdline=["python", "-m", "pytest"])

    assert OrphanDetector._is_safe_process(proc) is False


def test__is_safe_process_error_no_such_process():
    from app.shared.process.orphan_detector import OrphanDetector

    proc = FakeProc(1, name_error=no_such_process(1))

    assert OrphanDetector._is_safe_process(proc) is True


def test__is_safe_process_error_access_denied():
    from app.shared.process.orphan_detector import OrphanDetector

    proc = FakeProc(1, name_error=access_denied(1))

    assert OrphanDetector._is_safe_process(proc) is True


def test__is_safe_process_boundary_empty_cmdline():
    from app.shared.process.orphan_detector import OrphanDetector

    proc = FakeProc(1, name="python.exe", cmdline=[])

    assert OrphanDetector._is_safe_process(proc) is False


@pytest.mark.asyncio
async def test__scan_unregistered_right_finds_orphan_pytest():
    detector = make_detector({})
    proc = FakeProc(7001, ppid=9999, cmdline=["python", "-m", "pytest"])

    with patch("app.shared.process.orphan_detector.psutil.process_iter", return_value=[proc]), \
         patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False):
        result = await detector._scan_unregistered()

    assert len(result) == 1
    assert result[0]["pid"] == 7001
    assert result[0]["role"] == "unregistered_orphan"


@pytest.mark.asyncio
async def test__scan_unregistered_right_skips_alive_parent():
    detector = make_detector({})
    proc = FakeProc(7002, ppid=1234, cmdline=["python", "-m", "pytest"])

    with patch("app.shared.process.orphan_detector.psutil.process_iter", return_value=[proc]), \
         patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=True):
        result = await detector._scan_unregistered()

    assert result == []


@pytest.mark.asyncio
async def test__scan_unregistered_right_skips_registered():
    detector = make_detector({7003: make_entry(7003, 9999)})
    proc = FakeProc(7003, ppid=9999, cmdline=["python", "-m", "pytest"])

    with patch("app.shared.process.orphan_detector.psutil.process_iter", return_value=[proc]), \
         patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False):
        result = await detector._scan_unregistered()

    assert result == []


@pytest.mark.asyncio
async def test__scan_unregistered_right_skips_safe():
    detector = make_detector({})
    proc = FakeProc(7004, ppid=9999, cmdline=["python", "app.worker.main", "-m", "pytest"])

    with patch("app.shared.process.orphan_detector.psutil.process_iter", return_value=[proc]), \
         patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False):
        result = await detector._scan_unregistered()

    assert result == []


@pytest.mark.asyncio
async def test__scan_unregistered_boundary_no_cmdline():
    detector = make_detector({})
    proc = FakeProc(7005, ppid=9999, cmdline_error=access_denied(7005))

    with patch("app.shared.process.orphan_detector.psutil.process_iter", return_value=[proc]), \
         patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False):
        result = await detector._scan_unregistered()

    assert result == []


@pytest.mark.asyncio
async def test__scan_unregistered_boundary_non_python():
    detector = make_detector({})
    proc = FakeProc(7006, name="node.exe", ppid=9999, cmdline=["node", "pytest"])

    with patch("app.shared.process.orphan_detector.psutil.process_iter", return_value=[proc]), \
         patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False):
        result = await detector._scan_unregistered()

    assert result == []


@pytest.mark.asyncio
async def test__scan_unregistered_error_access_denied():
    detector = make_detector({})
    good = FakeProc(7007, ppid=9999, cmdline=["python", "-m", "pytest"])

    with patch("app.shared.process.orphan_detector.psutil.process_iter", return_value=[InfoAccessDeniedProc(), good]), \
         patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False):
        result = await detector._scan_unregistered()

    assert [item["pid"] for item in result] == [7007]


def test__collect_chain_right_descendants_first():
    child1 = FakeProc(8001, name="python.exe", cmdline=["python", "-m", "pytest"])
    child2 = FakeProc(8002, name="python.exe", cmdline=["python", "-m", "pytest"])
    target = FakeProc(8000, children=[child1, child2])
    detector = make_detector({})

    with patch("app.shared.process.orphan_detector.psutil.Process", return_value=target):
        assert detector._collect_chain(8000) == [8002, 8001, 8000]


def test__collect_chain_right_parent_cmd_sh():
    grandparent = FakeProc(8103, name="sh.exe", cmdline=["sh.exe", "pyenv"])
    parent = FakeProc(8102, name="cmd.exe", cmdline=["cmd.exe"], parent=grandparent)
    target = FakeProc(8101, parent=parent)
    detector = make_detector({})

    with patch("app.shared.process.orphan_detector.psutil.Process", return_value=target):
        assert detector._collect_chain(8101) == [8101, 8102, 8103]


def test__collect_chain_right_skips_safe_parent():
    parent = FakeProc(8202, name="nssm", cmdline=["nssm"])
    target = FakeProc(8201, parent=parent)
    detector = make_detector({})

    with patch("app.shared.process.orphan_detector.psutil.Process", return_value=target):
        assert detector._collect_chain(8201) == [8201]


def test__collect_chain_boundary_no_children():
    detector = make_detector({})
    target = FakeProc(8301, children=[])

    with patch("app.shared.process.orphan_detector.psutil.Process", return_value=target):
        assert detector._collect_chain(8301) == [8301]


def test__collect_chain_boundary_no_parent():
    detector = make_detector({})
    target = FakeProc(8401, parent=None)

    with patch("app.shared.process.orphan_detector.psutil.Process", return_value=target):
        assert detector._collect_chain(8401) == [8401]


def test__collect_chain_error_dead_process():
    detector = make_detector({})

    with patch("app.shared.process.orphan_detector.psutil.Process", side_effect=no_such_process(8501)):
        assert detector._collect_chain(8501) == []


@pytest.mark.asyncio
async def test_scan_finds_dead_parent():
    """R: ppid 죽은 프로세스 1개 등록 → scan() → orphan 1건 반환"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=1001, ppid=9999)
    registry = make_registry({1001: entry})

    def pid_exists(pid):
        if pid == 9999:
            return False  # ppid 죽음
        if pid == 1001:
            return True   # 자식은 살아있음
        return False

    detector = OrphanDetector(registry)
    with patch("app.shared.process.orphan_detector.psutil.pid_exists", side_effect=pid_exists), \
         patch.object(detector, "_scan_unregistered", AsyncMock(return_value=[])):
        orphans = await detector.scan()

    assert len(orphans) == 1
    assert orphans[0]["pid"] == "1001"


@pytest.mark.asyncio
async def test_scan_ignores_alive_parent():
    """I: ppid 살아있는 프로세스 → scan() → orphan 0건"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=2001, ppid=1000)
    registry = make_registry({2001: entry})

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=True):
        detector = OrphanDetector(registry)
        orphans = await detector.scan()

    assert len(orphans) == 0


@pytest.mark.asyncio
async def test_cleanup_grace_period_not_elapsed():
    """B: 감지 직후(0초) cleanup() → 정리 안 됨 (빈 리스트)"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=3001, ppid=9999)
    registry = make_registry({3001: entry})
    detector = OrphanDetector(registry, grace_period=30)

    # 방금 등록
    detector._orphan_first_seen[3001] = time.time()

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False):
        cleaned = await detector.cleanup([entry])

    assert len(cleaned) == 0


@pytest.mark.asyncio
async def test_cleanup_grace_period_elapsed():
    """R: _orphan_first_seen 30초 전으로 설정 → cleanup() → 정리됨"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=4001, ppid=9999)
    registry = make_registry({4001: entry})
    detector = OrphanDetector(registry, grace_period=30)

    # 31초 전으로 설정
    detector._orphan_first_seen[4001] = time.time() - 31

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False), \
         patch("app.shared.process.orphan_detector.kill_pid", return_value=True):
        cleaned = await detector.cleanup([entry])

    assert len(cleaned) == 1
    assert cleaned[0]["pid"] == "4001"


@pytest.mark.asyncio
async def test_cleanup_force_ignores_grace():
    """R: 감지 직후 cleanup(force=True) → 즉시 정리"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=5001, ppid=9999)
    registry = make_registry({5001: entry})
    detector = OrphanDetector(registry, grace_period=30)

    # 방금 등록
    detector._orphan_first_seen[5001] = time.time()

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False), \
         patch("app.shared.process.orphan_detector.kill_pid", return_value=True):
        cleaned = await detector.cleanup([entry], force=True)

    assert len(cleaned) == 1


@pytest.mark.asyncio
async def test_scan_removes_dead_processes():
    """E: pid 자체가 죽은 항목 → scan()에서 unregister 호출"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=6001, ppid=1000)
    registry = make_registry({6001: entry})
    detector = OrphanDetector(registry)

    def pid_exists(pid):
        if pid == 6001:
            return False  # 자신도 죽음
        return True

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", side_effect=pid_exists):
        await detector.scan()

    registry.unregister.assert_called_with(6001)


@pytest.mark.asyncio
async def test_scan_includes_unregistered_orphans():
    """R: Registry 고아와 미등록 고아를 함께 반환한다."""
    from app.shared.process.orphan_detector import OrphanDetector

    registered = make_entry(pid=6101, ppid=9999)
    registry = make_registry({6101: registered})
    detector = OrphanDetector(registry)
    unregistered = {
        "pid": 6102,
        "ppid": 9998,
        "name": "python.exe",
        "role": "unregistered_orphan",
    }

    def pid_exists(pid):
        return pid == 6101

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", side_effect=pid_exists), \
         patch.object(detector, "_scan_unregistered", AsyncMock(return_value=[unregistered])):
        orphans = await detector.scan()

    assert orphans == [registered, unregistered]


@pytest.mark.asyncio
async def test_scan_no_duplicates():
    """R: _scan_unregistered 자체가 등록 PID를 제외해 scan 결과가 중복되지 않는다."""
    detector = make_detector({6201: make_entry(6201, 9999)})
    proc = FakeProc(6201, ppid=9999, cmdline=["python", "-m", "pytest"])

    with patch("app.shared.process.orphan_detector.psutil.process_iter", return_value=[proc]), \
         patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False):
        result = await detector._scan_unregistered()

    assert result == []


@pytest.mark.asyncio
async def test_scan_unregistered_first_seen_recorded():
    """R: scan()이 미등록 고아의 최초 감지 시각을 기록한다."""
    detector = make_detector({})
    unregistered = {
        "pid": 6301,
        "ppid": 9998,
        "name": "python.exe",
        "role": "unregistered_orphan",
    }

    with patch.object(detector, "_scan_unregistered", AsyncMock(return_value=[unregistered])):
        await detector.scan()

    assert 6301 in detector._orphan_first_seen


@pytest.mark.asyncio
async def test_cleanup_chain_kill_unregistered():
    """R: role=unregistered_orphan이면 수집된 체인을 모두 종료한다."""
    entry = {
        "pid": 6402,
        "ppid": 9999,
        "name": "python.exe",
        "role": "unregistered_orphan",
    }
    detector = make_detector({}, grace_period=0)
    detector._orphan_first_seen[6402] = time.time() - 1

    with patch.object(detector, "_collect_chain", return_value=[6401, 6402, 6403]), \
         patch("app.shared.process.orphan_detector.kill_pid", return_value=True) as mock_kill, \
         patch("app.shared.process.snapshot_writer.SnapshotWriter"):
        cleaned = await detector.cleanup([entry])

    assert cleaned == [entry]
    assert [call.args[0] for call in mock_kill.call_args_list] == [6401, 6402, 6403]


@pytest.mark.asyncio
async def test_cleanup_chain_kill_order():
    """R: chain kill 순서는 _collect_chain 반환 순서를 그대로 따른다."""
    entry = {
        "pid": 6502,
        "ppid": 9999,
        "name": "python.exe",
        "role": "unregistered_orphan",
    }
    detector = make_detector({}, grace_period=0)
    detector._orphan_first_seen[6502] = time.time() - 1

    with patch.object(detector, "_collect_chain", return_value=[100, 200, 300]), \
         patch("app.shared.process.orphan_detector.kill_pid", return_value=True) as mock_kill, \
         patch("app.shared.process.snapshot_writer.SnapshotWriter"):
        await detector.cleanup([entry])

    assert [call.args[0] for call in mock_kill.call_args_list] == [100, 200, 300]


@pytest.mark.asyncio
async def test_cleanup_registered_unchanged():
    """R: 기존 registered orphan은 단일 pid kill + registry unregister 흐름을 유지한다."""
    entry = make_entry(pid=6601, ppid=9999)
    registry = make_registry({6601: entry})
    from app.shared.process.orphan_detector import OrphanDetector

    detector = OrphanDetector(registry, grace_period=0)
    detector._orphan_first_seen[6601] = time.time() - 1

    with patch("app.shared.process.orphan_detector.kill_pid", return_value=True) as mock_kill, \
         patch("app.shared.process.snapshot_writer.SnapshotWriter"):
        cleaned = await detector.cleanup([entry])

    assert cleaned == [entry]
    mock_kill.assert_called_once_with(6601)
    registry.unregister.assert_awaited_once_with(6601)


@pytest.mark.asyncio
async def test_cleanup_grace_period_unregistered():
    """R: 미등록 고아도 grace period 전에는 정리하지 않는다."""
    entry = {
        "pid": 6701,
        "ppid": 9999,
        "name": "python.exe",
        "role": "unregistered_orphan",
    }
    detector = make_detector({}, grace_period=30)
    detector._orphan_first_seen[6701] = time.time()

    with patch("app.shared.process.orphan_detector.kill_pid", return_value=True) as mock_kill:
        cleaned = await detector.cleanup([entry])

    assert cleaned == []
    mock_kill.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_unregistered_no_registry_unregister():
    """R: 미등록 고아 정리 시 registry.unregister는 호출하지 않는다."""
    entry = {
        "pid": 6801,
        "ppid": 9999,
        "name": "python.exe",
        "role": "unregistered_orphan",
    }
    registry = make_registry({})
    from app.shared.process.orphan_detector import OrphanDetector

    detector = OrphanDetector(registry, grace_period=0)
    detector._orphan_first_seen[6801] = time.time() - 1

    with patch.object(detector, "_collect_chain", return_value=[6801]), \
         patch("app.shared.process.orphan_detector.kill_pid", return_value=True), \
         patch("app.shared.process.snapshot_writer.SnapshotWriter"):
        cleaned = await detector.cleanup([entry])

    assert cleaned == [entry]
    registry.unregister.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_periodic_checks_memory_more_frequently_than_scan():
    """R: memory_check_interval < interval이면 pressure.check가 scan보다 더 자주 호출됨"""
    from app.shared.process.orphan_detector import OrphanDetector

    registry = make_registry({})
    detector = OrphanDetector(registry)
    detector.scan = AsyncMock(return_value=[])
    detector.cleanup = AsyncMock(return_value=[])
    detector.detect_orphan_test_worktrees = AsyncMock(return_value=[])
    detector._list_test_worktree_branches = MagicMock(return_value=[])

    fake_pressure = MagicMock()
    fake_pressure.check = AsyncMock(return_value="normal")

    with patch("app.shared.process.memory_pressure.MemoryPressureResponder", return_value=fake_pressure), \
         patch("app.shared.process.orphan_detector.settings.PROCESS_WATCH_CAPTURE_EVERY_LOOPS", 999), \
         patch("app.shared.process.orphan_detector.WorktreeResidueMonitor.record_scan"):
        task = asyncio.create_task(
            detector.run_periodic(interval=0.20, memory_check_interval=0.05)
        )
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            if fake_pressure.check.await_count > detector.scan.await_count:
                break
            await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert fake_pressure.check.await_count > detector.scan.await_count


@pytest.mark.asyncio
async def test_run_periodic_invokes_process_watch_capture_every_loop():
    """R: worker periodic 루프가 SnapshotWriter.capture_python_processes() 경로를 직접 호출한다."""
    from app.shared.process.orphan_detector import OrphanDetector

    registry = make_registry({})
    detector = OrphanDetector(registry)
    detector.scan = AsyncMock(return_value=[])
    detector.cleanup = AsyncMock(return_value=[])
    detector.detect_orphan_test_worktrees = AsyncMock(return_value=[])
    detector._list_test_worktree_branches = MagicMock(return_value=[])

    fake_pressure = MagicMock()
    fake_pressure.check = AsyncMock(return_value="normal")
    fake_writer = MagicMock()
    fake_writer.capture_python_processes = AsyncMock(return_value=1)

    with patch("app.shared.process.memory_pressure.MemoryPressureResponder", return_value=fake_pressure), \
         patch("app.shared.process.snapshot_writer.SnapshotWriter", return_value=fake_writer), \
         patch("app.shared.process.orphan_detector.settings.PROCESS_WATCH_CAPTURE_EVERY_LOOPS", 1), \
         patch("app.shared.process.orphan_detector.settings.PROCESS_WATCH_CAPTURE_TIMEOUT_SEC", 2), \
         patch("app.shared.process.orphan_detector.settings.PROCESS_WATCH_CAPTURE_LIMIT", 17), \
         patch("app.shared.process.orphan_detector.WorktreeResidueMonitor.record_scan"):
        task = asyncio.create_task(detector.run_periodic(interval=0.05, memory_check_interval=0.50))
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline and fake_writer.capture_python_processes.await_count == 0:
            await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    fake_writer.capture_python_processes.assert_awaited()
    kwargs = fake_writer.capture_python_processes.await_args.kwargs
    assert kwargs["limit"] == 17
    assert kwargs["captured_by"] == "periodic"


@pytest.mark.asyncio
async def test_run_periodic_capture_failure_is_logged_and_loop_continues(caplog):
    """R: periodic capture 실패는 worker 루프를 죽이지 않고 warning 후 scan/cleanup을 계속한다."""
    from app.shared.process.orphan_detector import OrphanDetector

    registry = make_registry({})
    detector = OrphanDetector(registry)
    detector.scan = AsyncMock(return_value=[])
    detector.cleanup = AsyncMock(return_value=[])
    detector.detect_orphan_test_worktrees = AsyncMock(return_value=[])
    detector._list_test_worktree_branches = MagicMock(return_value=[])

    fake_pressure = MagicMock()
    fake_pressure.check = AsyncMock(return_value="normal")
    fake_writer = MagicMock()
    fake_writer.capture_python_processes = AsyncMock(side_effect=RuntimeError("pg write failed"))

    caplog.set_level(logging.WARNING)
    with patch("app.shared.process.memory_pressure.MemoryPressureResponder", return_value=fake_pressure), \
         patch("app.shared.process.snapshot_writer.SnapshotWriter", return_value=fake_writer), \
         patch("app.shared.process.orphan_detector.settings.PROCESS_WATCH_CAPTURE_EVERY_LOOPS", 1), \
         patch("app.shared.process.orphan_detector.settings.PROCESS_WATCH_CAPTURE_TIMEOUT_SEC", 2), \
         patch("app.shared.process.orphan_detector.WorktreeResidueMonitor.record_scan"):
        task = asyncio.create_task(detector.run_periodic(interval=0.05, memory_check_interval=0.50))
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline and detector.scan.await_count == 0:
            await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert detector.scan.await_count >= 1
    assert any("periodic capture failed" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_detect_orphan_test_worktrees_finds_stale_runner(tmp_path):
    """R: stale runner/t-* worktree + Redis 키 없음 → cleanup 후보 반환"""
    from app.shared.process.orphan_detector import OrphanDetector

    worktree = tmp_path / ".worktrees" / "t-stale-001"
    worktree.mkdir(parents=True)
    stale_time = time.time() - 1200
    import os
    os.utime(worktree, (stale_time, stale_time))

    detector = OrphanDetector(
        make_registry({}),
        repo_root=tmp_path,
        runner_key_exists=lambda _runner_id: False,
    )

    with patch.object(
        detector,
        "_iter_git_worktrees",
        return_value=[{"branch": "runner/t-stale-001", "worktree_path": str(worktree)}],
    ):
        branches = await detector.detect_orphan_test_worktrees()

    assert branches == ["runner/t-stale-001"]


@pytest.mark.asyncio
async def test_detect_orphan_test_worktrees_skips_non_test_prefix(tmp_path):
    """I: impl/* 브랜치는 후보에서 제외"""
    from app.shared.process.orphan_detector import OrphanDetector

    worktree = tmp_path / ".worktrees" / "impl-fix"
    worktree.mkdir(parents=True)
    stale_time = time.time() - 1200
    import os
    os.utime(worktree, (stale_time, stale_time))

    detector = OrphanDetector(make_registry({}), repo_root=tmp_path)

    with patch.object(
        detector,
        "_iter_git_worktrees",
        return_value=[{"branch": "impl/fix-foo", "worktree_path": str(worktree)}],
    ):
        branches = await detector.detect_orphan_test_worktrees()

    assert branches == []


@pytest.mark.asyncio
async def test_detect_orphan_test_worktrees_skips_active_runner(tmp_path):
    """I: runner 키가 남아 있으면 후보에서 제외"""
    from app.shared.process.orphan_detector import OrphanDetector

    worktree = tmp_path / ".worktrees" / "t-active-001"
    worktree.mkdir(parents=True)
    stale_time = time.time() - 1200
    import os
    os.utime(worktree, (stale_time, stale_time))

    detector = OrphanDetector(
        make_registry({}),
        repo_root=tmp_path,
        runner_key_exists=lambda _runner_id: True,
    )

    with patch.object(
        detector,
        "_iter_git_worktrees",
        return_value=[{"branch": "runner/t-active-001", "worktree_path": str(worktree)}],
    ):
        branches = await detector.detect_orphan_test_worktrees()

    assert branches == []


@pytest.mark.asyncio
async def test_detect_orphan_test_worktrees_respects_age_threshold(tmp_path):
    """B: 15분 경계 전후만 후보 여부가 갈려야 한다"""
    from app.shared.process.orphan_detector import OrphanDetector

    early = tmp_path / ".worktrees" / "t-early-001"
    exact = tmp_path / ".worktrees" / "t-exact-001"
    stale = tmp_path / ".worktrees" / "t-stale-001"
    for worktree in (early, exact, stale):
        worktree.mkdir(parents=True)

    now = time.time()
    import os

    os.utime(early, (now - 899, now - 899))
    os.utime(exact, (now - 900, now - 900))
    os.utime(stale, (now - 901, now - 901))

    detector = OrphanDetector(
        make_registry({}),
        repo_root=tmp_path,
        runner_key_exists=lambda _runner_id: False,
    )

    with patch.object(
        detector,
        "_iter_git_worktrees",
        return_value=[
            {"branch": "runner/t-early-001", "worktree_path": str(early)},
            {"branch": "runner/t-exact-001", "worktree_path": str(exact)},
            {"branch": "runner/t-stale-001", "worktree_path": str(stale)},
        ],
    ):
        branches = await detector.detect_orphan_test_worktrees()

    assert "runner/t-early-001" not in branches
    assert "runner/t-exact-001" in branches
    assert "runner/t-stale-001" in branches


@pytest.mark.asyncio
async def test_run_periodic_invokes_test_worktree_cleanup():
    """R: stale test worktree가 감지되면 cleanup callback까지 연결된다"""
    from app.shared.process.orphan_detector import OrphanDetector

    registry = make_registry({})
    cleanup_callback = AsyncMock(return_value=None)
    detector = OrphanDetector(registry, cleanup_callback=cleanup_callback)
    detector.scan = AsyncMock(return_value=[])
    detector.cleanup = AsyncMock(return_value=[])
    detector.detect_orphan_test_worktrees = AsyncMock(return_value=["runner/t-stale-002"])
    detector._list_test_worktree_branches = MagicMock(return_value=[])

    fake_pressure = MagicMock()
    fake_pressure.check = AsyncMock(return_value="normal")

    with patch("app.shared.process.memory_pressure.MemoryPressureResponder", return_value=fake_pressure), \
         patch("app.shared.process.orphan_detector.settings.PROCESS_WATCH_CAPTURE_EVERY_LOOPS", 999), \
         patch("app.shared.process.orphan_detector.WorktreeResidueMonitor.record_cleanup") as mock_record_cleanup, \
         patch("app.shared.process.orphan_detector.WorktreeResidueMonitor.record_scan") as mock_record_scan:
        task = asyncio.create_task(
            detector.run_periodic(interval=0.20, memory_check_interval=0.20)
        )
        await asyncio.sleep(0.22)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    cleanup_callback.assert_awaited_with(["runner/t-stale-002"])
    mock_record_cleanup.assert_called_with(
        event_type="orphan_cleanup",
        branches=["runner/t-stale-002"],
        source="orphan_detector",
        repo_root=detector.repo_root,
    )
    mock_record_scan.assert_called_with([], source="orphan_detector", repo_root=detector.repo_root)
