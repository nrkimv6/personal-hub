"""실제 subprocess tree cleanup 검증."""

import subprocess
import time
from pathlib import Path

import psutil

from tests.dev_runner._path_helpers import get_project_python


def _wait_for_pid_file(pid_file: Path, timeout: float = 5.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pid_file.exists():
            text = pid_file.read_text(encoding="utf-8").strip()
            if text:
                return int(text)
        time.sleep(0.05)
    raise AssertionError(f"child PID file was not written: {pid_file}")


def _wait_until_pid_exits(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not psutil.pid_exists(pid):
            return True
        time.sleep(0.05)
    return not psutil.pid_exists(pid)


def test_kill_tree_terminates_real_child(tmp_path):
    """T3: 실제 부모 process 아래 생성된 child process를 tree helper가 종료한다."""
    from _dr_plan_runner import _kill_process_tree

    python = get_project_python()
    pid_file = tmp_path / "child.pid"
    parent_code = (
        "import pathlib, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8'); "
        "time.sleep(60)"
    )
    parent = subprocess.Popen(
        [python, "-c", parent_code, str(pid_file)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child_pid = None
    try:
        child_pid = _wait_for_pid_file(pid_file)
        assert psutil.pid_exists(child_pid)

        _kill_process_tree(parent.pid, timeout=2)

        assert _wait_until_pid_exits(child_pid), f"child process still alive: {child_pid}"
    finally:
        if child_pid and psutil.pid_exists(child_pid):
            try:
                psutil.Process(child_pid).kill()
            except psutil.NoSuchProcess:
                pass
        if parent.poll() is None:
            parent.kill()
        try:
            parent.wait(timeout=5)
        except subprocess.TimeoutExpired:
            parent.kill()
            parent.wait(timeout=5)


def test_kill_tree_already_dead():
    """T3: 이미 종료된 PID에 대한 cleanup 호출은 예외 없이 반환한다."""
    from _dr_plan_runner import _kill_process_tree

    python = get_project_python()
    proc = subprocess.Popen([python, "-c", "pass"])
    proc.wait(timeout=5)

    _kill_process_tree(proc.pid, timeout=1)
