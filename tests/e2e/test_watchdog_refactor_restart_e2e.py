"""
T4 E2E: watchdog refactor restart smoke

main runtime에서 browser_workers.py restart 이후
refactor된 watchdog 3개 축(claude/chat_executor/command_listener)의
PID 파일과 최신 watchdog 로그가 유지되는지 확인한다.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE = "http://localhost:8001"
PID_DIR = PROJECT_ROOT / ".pids"
LOG_DIR = PROJECT_ROOT / "logs" / "admin"

pytestmark = pytest.mark.e2e


def _python() -> str:
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv_python) if venv_python.exists() else sys.executable


def _is_api_up() -> bool:
    try:
        resp = httpx.get(f"{BASE}/api/v1/system/liveness", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


def _watchdogs_running() -> bool:
    try:
        resp = httpx.get(f"{BASE}/api/v1/system/services/workers", timeout=5.0)
        if resp.status_code != 200:
            return False
        data = resp.json()
    except Exception:
        return False

    required = {"claude_worker", "chat_executor", "command_listener"}
    names = {
        item.get("name")
        for item in data
        if item.get("watchdog", {}).get("running") is True
    }
    return required.issubset(names)


@pytest.fixture(autouse=True)
def skip_if_not_ready():
    if not _is_api_up():
        pytest.skip("live API(localhost:8001) 미기동 — skip")
    if not _watchdogs_running():
        pytest.skip("필수 watchdog 3종이 실행 중이 아님 — skip")


def _latest_mtime(pattern: str) -> float:
    logs = list(LOG_DIR.glob(pattern))
    if not logs:
        return 0.0
    return max(p.stat().st_mtime for p in logs)


def _wait_for_pid_file(name: str, after_mtime: float, timeout: float = 30) -> bool:
    target = PID_DIR / name
    deadline = time.time() + timeout
    while time.time() < deadline:
        if target.exists() and target.stat().st_mtime >= after_mtime:
            return True
        time.sleep(1.0)
    return False


def _wait_for_log(pattern: str, after_mtime: float, timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        matches = [p for p in LOG_DIR.glob(pattern) if p.stat().st_mtime >= after_mtime]
        if matches:
            return True
        time.sleep(1.0)
    return False


def test_watchdog_restart_e2e_smoke():
    browser_workers = PROJECT_ROOT / "scripts" / "services" / "browser_workers.py"

    before = time.time()
    command_listener_log_mtime = _latest_mtime("command_listener_watchdog_*.log")
    claude_log_mtime = _latest_mtime("claude_watchdog_*.log")
    chat_log_mtime = _latest_mtime("chat_executor_watchdog_*.log")

    result = subprocess.run(
        [_python(), str(browser_workers), "restart"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(PROJECT_ROOT),
        timeout=60,
    )
    assert result.returncode == 0, (
        f"restart 실패: returncode={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )

    assert _wait_for_pid_file("claude_worker_admin.pid", before), "claude_worker_admin.pid 갱신 실패"
    assert _wait_for_pid_file("chat_executor_admin.pid", before), "chat_executor_admin.pid 갱신 실패"
    assert _wait_for_pid_file("command_listener_admin.pid", before), "command_listener_admin.pid 갱신 실패"

    assert _wait_for_log("claude_watchdog_*.log", claude_log_mtime), "claude watchdog log 갱신 실패"
    assert _wait_for_log("chat_executor_watchdog_*.log", chat_log_mtime), "chat executor watchdog log 갱신 실패"
    assert _wait_for_log("command_listener_watchdog_*.log", command_listener_log_mtime), "command listener watchdog log 갱신 실패"
