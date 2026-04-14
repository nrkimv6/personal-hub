"""Shared runtime helpers for browser worker management."""

import os
import sys
import time
from pathlib import Path

import psutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"


def cprint(msg: str, color: str = RESET):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{GRAY}[{ts}]{RESET} {color}{msg}{RESET}")


def _kill_by_cmdline(pattern: str) -> int:
    """Terminate processes whose cmdline contains pattern.

    Returns the number of processes killed. Self and all ancestor processes
    are excluded to avoid killing the running CLI context.
    """
    self_pid = os.getpid()
    excluded_pids = {self_pid}
    try:
        for parent in psutil.Process(self_pid).parents():
            excluded_pids.add(parent.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    killed = 0
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.pid in excluded_pids:
                continue
            cmdline = proc.info.get("cmdline") or []
            if any(pattern in arg for arg in cmdline):
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed
