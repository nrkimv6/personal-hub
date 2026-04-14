"""Facade for browser worker management CLI."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.shared.process.tracked_popen import tracked_popen_sync
from scripts.services.browser_worker_runtime import (
    BOLD,
    CYAN,
    GRAY,
    GREEN,
    PROJECT_ROOT,
    RED,
    RESET,
    YELLOW,
    BrowserWorkerManager,
    cprint,
    _kill_by_cmdline,
)
from scripts.services.browser_worker_runtime.cli import main as _cli_main
from scripts.services.service_utils import (
    find_pids_on_port,
    is_port_listening,
    is_process_alive,
    kill_pid,
    pick_listener_pid,
    read_pid_file,
    remove_pid_file,
    write_pid_file,
)

__all__ = [
    "BOLD",
    "CYAN",
    "GRAY",
    "GREEN",
    "PROJECT_ROOT",
    "RED",
    "RESET",
    "YELLOW",
    "BrowserWorkerManager",
    "cprint",
    "main",
    "_kill_by_cmdline",
    "tracked_popen_sync",
    "find_pids_on_port",
    "is_port_listening",
    "is_process_alive",
    "kill_pid",
    "pick_listener_pid",
    "read_pid_file",
    "remove_pid_file",
    "write_pid_file",
    "subprocess",
    "time",
    "urllib",
]


def main() -> int:
    raise SystemExit(_cli_main(BrowserWorkerManager))


if __name__ == "__main__":
    main()
