"""OrphanDetector process-level integration tests."""
import subprocess
import sys
import time

import psutil
import pytest

from tests.test_process_tracker.test_orphan_detector import make_registry


def _terminate(pid: int) -> None:
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except psutil.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _wait_for_process(pid: int, timeout: float = 10.0) -> psutil.Process:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            proc = psutil.Process(pid)
            if proc.is_running():
                return proc
        except psutil.Error as exc:
            last_error = exc
        time.sleep(0.1)
    raise AssertionError(f"process {pid} did not become available: {last_error}")


@pytest.mark.asyncio
async def test_scan_unregistered_real_orphan_process():
    """T3: 실제 부모 종료 후 남은 pytest-like python 프로세스를 미등록 고아로 탐지한다."""
    from app.shared.process.orphan_detector import OrphanDetector

    parent_code = (
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'pytest-orphan-sentinel'])\n"
        "print(child.pid, flush=True)\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_pid = 0
    try:
        raw_pid = parent.stdout.readline().strip() if parent.stdout is not None else ""
        child_pid = int(raw_pid)
        parent.wait(timeout=10)
        child_proc = _wait_for_process(child_pid)

        detector = OrphanDetector(make_registry({}))
        deadline = time.monotonic() + 10
        result = []
        while time.monotonic() < deadline:
            result = await detector._scan_unregistered()
            if any(item["pid"] == child_pid for item in result):
                break
            time.sleep(0.2)

        matched = [item for item in result if item["pid"] == child_pid]
        assert matched
        assert matched[0]["role"] == "unregistered_orphan"
        assert "pytest-orphan-sentinel" in matched[0]["cmdline_short"]
        assert not psutil.pid_exists(child_proc.ppid())
    finally:
        if child_pid:
            _terminate(child_pid)
        if parent.poll() is None:
            parent.kill()


def test_collect_chain_real_process_tree():
    """T3: 실제 parent→child python 트리에서 child가 본체보다 먼저 수집된다."""
    from app.shared.process.orphan_detector import OrphanDetector

    parent_code = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'pytest-child-sentinel'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_code, "pytest-parent-sentinel"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_pid = 0
    try:
        raw_pid = parent.stdout.readline().strip() if parent.stdout is not None else ""
        child_pid = int(raw_pid)
        _wait_for_process(child_pid)

        detector = OrphanDetector(make_registry({}))
        chain = detector._collect_chain(parent.pid)

        assert child_pid in chain
        assert parent.pid in chain
        assert chain.index(child_pid) < chain.index(parent.pid)
    finally:
        if child_pid:
            _terminate(child_pid)
        _terminate(parent.pid)
