"""OrphanDetector periodic-loop E2E-style tests."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.shared.process.orphan_detector import OrphanDetector
from app.shared.process.memory_pressure import MemoryPressureResponder


def make_registry(procs: dict):
    registry = MagicMock()
    registry.get_all = AsyncMock(return_value=procs)
    registry.unregister = AsyncMock(return_value=True)
    return registry


class FakeMem:
    rss = 10 * 1024 * 1024


class FakeProc:
    def __init__(self, pid: int, ppid: int, cmdline: list[str] | None = None):
        self.pid = pid
        self.info = {"pid": pid, "name": "python.exe", "ppid": ppid}
        self._cmdline = cmdline or ["python", "-m", "pytest", "tests/test_target.py"]

    def name(self):
        return "python.exe"

    def cmdline(self):
        return self._cmdline

    def memory_info(self):
        return FakeMem()


@pytest.mark.asyncio
async def test_run_periodic_detects_unregistered_orphan():
    registry = make_registry({})
    detector = OrphanDetector(registry)
    detector._orphan_first_seen[4567] = time.time() - detector.grace_period - 1
    detector._collect_chain = MagicMock(return_value=[4567])
    detector.detect_orphan_test_worktrees = AsyncMock(return_value=[])
    detector._list_test_worktree_branches = MagicMock(return_value=[])

    fake_pressure = MagicMock()
    fake_pressure.check = AsyncMock(return_value="normal")
    fake_proc = FakeProc(pid=4567, ppid=999999)

    with patch("app.shared.process.orphan_detector.psutil.process_iter", return_value=[fake_proc]), \
         patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False), \
         patch("app.shared.process.orphan_detector.kill_pid", return_value=True) as mock_kill_pid, \
         patch("app.shared.process.orphan_detector.settings.PROCESS_WATCH_CAPTURE_EVERY_LOOPS", 999), \
         patch("app.shared.process.memory_pressure.MemoryPressureResponder", return_value=fake_pressure), \
         patch("app.shared.process.orphan_detector.WorktreeResidueMonitor.record_scan"):
        task = asyncio.create_task(detector.run_periodic(interval=0.20, memory_check_interval=10.0))
        await asyncio.sleep(0.24)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    mock_kill_pid.assert_called_once_with(4567)
    fake_pressure.check.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_periodic_memory_pressure_triggers_force_cleanup():
    registry = make_registry({})
    detector = OrphanDetector(registry)
    orphan = {
        "pid": 7890,
        "ppid": 999999,
        "name": "python.exe",
        "role": "unregistered_orphan",
        "cmdline_short": "python -m pytest tests/test_target.py",
        "memory_mb": 10.0,
    }
    detector.scan = AsyncMock(return_value=[orphan])
    detector.cleanup = AsyncMock(return_value=[orphan])

    pressure = MemoryPressureResponder(detector)
    virtual_memory = SimpleNamespace(available=768 * 1024 * 1024)

    with patch("app.shared.process.memory_pressure.psutil.virtual_memory", return_value=virtual_memory), \
         patch.object(pressure, "_get_top_processes", return_value=[]), \
         patch.object(pressure, "_persist_snapshot"), \
         patch("app.shared.process.memory_pressure._collect_process_tree", return_value=[]), \
         patch("app.shared.process.memory_pressure._format_process_tree", return_value=""):
        level = await pressure.check()

    assert level == "critical"
    detector.scan.assert_awaited_once()
    detector.cleanup.assert_awaited_once_with([orphan], force=True)
