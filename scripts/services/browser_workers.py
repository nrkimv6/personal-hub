"""Facade for browser worker management CLI."""

import argparse
import sys
from pathlib import Path
import subprocess
import time
import urllib

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
    main,
    _kill_by_cmdline,
)
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


def main():
    if "--restart-frontend" in sys.argv[1:]:
        print(
            "error: '--restart-frontend' is not a valid option. "
            "Use positional action: python scripts/services/browser_workers.py restart-frontend [--public]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    parser = argparse.ArgumentParser(description="Browser Workers Management")
    parser.add_argument(
        "action",
        choices=["start", "stop", "restart", "status", "restart-api", "restart-frontend", "redis-status", "redis-restart", "redis-cleanup", "restart-listener", "restart-infra"],
        help="Action to perform",
    )
    parser.add_argument("target", nargs="?", default=None, help="Target name for restart-infra")
    parser.add_argument(
        "--public",
        action="store_true",
        help="Use PUBLIC PREVIEW mode for restart-frontend (port 6100, build+preview)",
    )
    args = parser.parse_args()

    if args.public and args.action != "restart-frontend":
        parser.error("--public can only be used with restart-frontend")
    if args.action == "restart-infra" and not args.target:
        parser.error("restart-infra requires target argument")

    mgr = BrowserWorkerManager()
    action_map = {
        "start": mgr.start,
        "stop": mgr.stop,
        "restart": mgr.restart,
        "status": mgr.status,
        "restart-api": mgr.restart_api,
        "redis-status": mgr.redis_status,
        "redis-restart": mgr.redis_restart,
        "redis-cleanup": mgr.redis_cleanup,
        "restart-listener": mgr.restart_listener,
        "restart-infra": lambda: mgr.restart_infra(args.target or ""),
    }
    if args.action == "restart-frontend":
        ok = mgr.restart_frontend(public=args.public)
        raise SystemExit(0 if ok else 1)
    action_map[args.action]()


if __name__ == "__main__":
    raise SystemExit(main())
