"""CLI parser/dispatcher for browser workers."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browser Workers Management")
    parser.add_argument(
        "action",
        choices=[
            "start",
            "stop",
            "restart",
            "status",
            "restart-api",
            "restart-frontend",
            "redis-status",
            "redis-restart",
            "redis-cleanup",
            "restart-listener",
            "restart-infra",
        ],
        help="Action to perform",
    )
    parser.add_argument("target", nargs="?", default=None, help="Target name for restart-infra")
    parser.add_argument(
        "--public",
        action="store_true",
        help="Use PUBLIC PREVIEW mode for restart-frontend (port 6100, build+preview)",
    )
    return parser


def main(manager_cls, argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if "--restart-frontend" in argv:
        print(
            "error: '--restart-frontend' is not a valid option. "
            "Use positional action: python scripts/services/browser_workers.py restart-frontend [--public]",
            file=sys.stderr,
        )
        return 2

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.public and args.action != "restart-frontend":
        parser.error("--public can only be used with restart-frontend")
    if args.action == "restart-infra" and not args.target:
        parser.error("restart-infra requires target argument")

    mgr = manager_cls()
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
        return 0 if ok else 1

    action_map[args.action]()
    return 0
