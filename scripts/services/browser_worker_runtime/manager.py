"""Browser Workers runtime manager.

Usage:
  Service commands must be run from the root checkout, not .worktrees/*.
  python scripts/services/browser_workers.py start
  python scripts/services/browser_workers.py stop
  python scripts/services/browser_workers.py restart
  python scripts/services/browser_workers.py status
  python scripts/services/browser_workers.py restart-api
  python scripts/services/browser_workers.py restart-api --public
  python scripts/services/browser_workers.py restart-frontend
  python scripts/services/browser_workers.py restart-frontend --public
"""
import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from app.shared.process.tracked_popen import tracked_popen_sync
from scripts.services.browser_worker_runtime.runtime import (
    BOLD,
    CYAN,
    GRAY,
    GREEN,
    PROJECT_ROOT,
    RED,
    RESET,
    YELLOW,
    cprint,
    assert_repo_root_checkout,
    _kill_by_cmdline,
)
from scripts.services.browser_worker_runtime.frontend_actions import (
    _acquire_frontend_restart_lock as _acquire_frontend_restart_lock_impl,
    _cleanup_frontend_runtime as _cleanup_frontend_runtime_impl,
    _frontend_mode as _frontend_mode_impl,
    _frontend_runtime_env as _frontend_runtime_env_impl,
    _has_port_collision_error as _has_port_collision_error_impl,
    _prepare_frontend_env as _prepare_frontend_env_impl,
    _print_frontend_status as _print_frontend_status_impl,
    _release_frontend_restart_lock as _release_frontend_restart_lock_impl,
    _run_frontend_build_if_needed as _run_frontend_build_if_needed_impl,
    restart_frontend as restart_frontend_impl,
)
from scripts.services.browser_worker_runtime.api_actions import (
    _check_wmi_health as _check_wmi_health_impl,
    _fix_wmi as _fix_wmi_impl,
    _nssm_restart_elevated as _nssm_restart_elevated_impl,
    restart_api as restart_api_impl,
)
from scripts.services.browser_worker_runtime.status_actions import (
    _print_redis_status as _print_redis_status_impl,
    redis_cleanup as redis_cleanup_impl,
    redis_restart as redis_restart_impl,
    redis_status as redis_status_impl,
    status as status_impl,
)
from scripts.services.browser_worker_runtime.listener_infra_actions import (
    restart_infra as restart_infra_impl,
    restart_listener as restart_listener_impl,
)
from scripts.services.browser_worker_runtime.watchdog_actions import (
    _cleanup_legacy as _cleanup_legacy_impl,
    restart as restart_impl,
    start as start_impl,
    stop as stop_impl,
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


class BrowserWorkerManager:
    def __init__(self):
        assert_repo_root_checkout()
        self.pid_dir = PROJECT_ROOT / ".pids"
        self.log_dir = PROJECT_ROOT / "logs" / "admin"
        self.scripts_dir = PROJECT_ROOT / "scripts"
        self.watchdogs_dir = PROJECT_ROOT / "scripts" / "watchdogs"
        self.frontend_dir = PROJECT_ROOT / "frontend"
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.pid_suffix = "_admin"
        self.app_mode = "admin"
        self.api_port = 8001
        self.frontend_port = 6101
        self.frontend_restart_lock = self.pid_dir / "frontend_restart.lock"

        # venv python — use exe alias if available, fallback to python.exe
        alias_exe = PROJECT_ROOT / ".venv" / "Scripts" / "monitorpage-worker.exe"
        if alias_exe.exists():
            self.python_exe = alias_exe
        else:
            self.python_exe = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
            if not self.python_exe.exists():
                self.python_exe = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"

        def _ps_alias(name: str) -> str:
            ps_alias_exe = PROJECT_ROOT / ".venv" / "Scripts" / name
            return str(ps_alias_exe) if ps_alias_exe.exists() else "powershell.exe"

        # Watchdog/Listener 정의: (이름, PID파일명, 시작 명령)
        self.workers = [
            {
                "name": "Worker Watchdog (all workers via WorkerOrchestrator)",
                "pid_file": f"worker_watchdog{self.pid_suffix}.pid",
                "cmd": [_ps_alias("monitorpage-wdog-worker.exe"), "-ExecutionPolicy", "Bypass", "-File",
                        str(self.watchdogs_dir / "unified-worker-watchdog.ps1")],
                "env": {"APP_MODE": "admin"},
                "role": "watchdog",
            },
            {
                "name": "Claude Worker Watchdog",
                "pid_file": f"claude_watchdog{self.pid_suffix}.pid",
                "cmd": [_ps_alias("monitorpage-wdog-claude.exe"), "-ExecutionPolicy", "Bypass", "-File",
                        str(self.watchdogs_dir / "claude-watchdog.ps1")],
                "env": {"APP_MODE": "admin"},
                "role": "claude_watchdog",
            },
            {
                "name": "Command Listener Watchdog",
                "pid_file": f"command_listener_watchdog{self.pid_suffix}.pid",
                "cmd": [_ps_alias("monitorpage-wdog-cmd.exe"), "-ExecutionPolicy", "Bypass", "-File",
                        str(self.watchdogs_dir / "command-listener-watchdog.ps1")],
                "env": {"APP_MODE": "admin"},
                "role": "listener",
            },
            {
                "name": "Kakao Notification Watchdog",
                "pid_file": f"kakao_notification_watchdog{self.pid_suffix}.pid",
                "cmd": [_ps_alias("monitorpage-wdog-kakao.exe"), "-ExecutionPolicy", "Bypass", "-File",
                        str(self.watchdogs_dir / "kakao-notification-watchdog.ps1")],
                "env": {"APP_MODE": "admin"},
                "role": "listener",
            },
            {
                "name": "Dev Runner Listener Watchdog",
                "pid_file": f"dev_runner_watchdog{self.pid_suffix}.pid",
                "cmd": [_ps_alias("monitorpage-wdog-devrunner.exe"), "-ExecutionPolicy", "Bypass", "-File",
                        str(self.watchdogs_dir / "dev-runner-listener-watchdog.ps1")],
                "env": {"APP_MODE": "admin"},
                "role": "dev_listener",
            },
            {
                "name": "Chat Executor Watchdog",
                "pid_file": f"chat_executor_watchdog{self.pid_suffix}.pid",
                "cmd": [_ps_alias("monitorpage-wdog-chat.exe"), "-ExecutionPolicy", "Bypass", "-File",
                        str(self.watchdogs_dir / "llm-chat-executor-watchdog.ps1")],
                "env": {"APP_MODE": "admin"},
                "role": "watchdog",
            },
        ]

        # 실제 워커 프로세스 PID 파일 (stop 시 정리)
        self.worker_pid_files = [
            f"unified_worker{self.pid_suffix}.pid",
            f"claude_worker{self.pid_suffix}.pid",
            f"command_listener{self.pid_suffix}.pid",
            f"dev_runner_command_listener{self.pid_suffix}.pid",  # watchdog가 관리하는 worker PID
            f"chat_executor_admin.pid",
            "kakao_notification_listener.pid",
        ]

        # Legacy PID 파일
        self.legacy_pid_files = [
            f"watchdog{self.pid_suffix}.pid",
            f"crawl_watchdog{self.pid_suffix}.pid",
            f"worker{self.pid_suffix}.pid",
            f"crawl_worker{self.pid_suffix}.pid",
            # video-dl이 orchestrator로 통합됨 (이전 별도 watchdog 정리용)
            f"video_download_watchdog{self.pid_suffix}.pid",
            f"video_download_worker{self.pid_suffix}.pid",
        ]

    def start(self):
        return start_impl(self)

    def stop(self):
        return stop_impl(self)

    def restart(self):
        return restart_impl(self)

    def _check_wmi_health(self) -> bool:
        return _check_wmi_health_impl(self)

    def _fix_wmi(self) -> bool:
        return _fix_wmi_impl(self)

    def _nssm_restart_elevated(self, service_name: str) -> bool:
        return _nssm_restart_elevated_impl(self, service_name)

    def restart_api(self, public: bool = False):
        return restart_api_impl(self, public=public)

    # ── restart-frontend ─────────────────────────────────────────
    def _frontend_mode(self, public: bool) -> tuple[str, int, int, Path, Path]:
        return _frontend_mode_impl(self, public)

    def _acquire_frontend_restart_lock(self, wait_seconds: int = 10) -> int | None:
        return _acquire_frontend_restart_lock_impl(self, wait_seconds=wait_seconds)

    def _release_frontend_restart_lock(self, lock_fd: int | None) -> None:
        return _release_frontend_restart_lock_impl(self, lock_fd)

    def _cleanup_frontend_runtime(self, frontend_port: int, pid_file: Path) -> None:
        return _cleanup_frontend_runtime_impl(self, frontend_port, pid_file)

    def _prepare_frontend_env(self, api_port: int, public: bool) -> None:
        return _prepare_frontend_env_impl(self, api_port, public)

    def _frontend_runtime_env(self, public: bool) -> dict[str, str]:
        return _frontend_runtime_env_impl(self, public)

    def _run_frontend_build_if_needed(
        self,
        public: bool,
        frontend_env: dict[str, str] | None = None,
        *,
        timestamp: str | None = None,
        log_dir: Path | None = None,
    ) -> bool:
        return _run_frontend_build_if_needed_impl(
            self,
            public,
            frontend_env=frontend_env,
            timestamp=timestamp,
            log_dir=log_dir,
        )

    def _has_port_collision_error(self, stderr_log_path: Path, frontend_port: int) -> bool:
        return _has_port_collision_error_impl(self, stderr_log_path, frontend_port)

    def restart_frontend(self, public: bool = False) -> bool:
        return restart_frontend_impl(self, public=public)

    def _print_frontend_status(self, public: bool = False):
        return _print_frontend_status_impl(self, public=public)

    def _print_redis_status(self):
        return _print_redis_status_impl(self)

    def status(self):
        return status_impl(self)

    def redis_status(self):
        return redis_status_impl(self)

    def redis_restart(self):
        return redis_restart_impl(self)

    def redis_cleanup(self, dry_run: bool = False):
        return redis_cleanup_impl(self, dry_run=dry_run)

    def restart_listener(self):
        return restart_listener_impl(self)

    def restart_infra(self, target: str):
        return restart_infra_impl(self, target)

    def _cleanup_legacy(self):
        return _cleanup_legacy_impl(self)


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
        help="Use public mode for restart-api (port 8000) or restart-frontend (port 6100, build+preview)",
    )
    args = parser.parse_args()

    if args.public and args.action not in {"restart-api", "restart-frontend"}:
        parser.error("--public can only be used with restart-api or restart-frontend")
    if args.action == "restart-infra" and not args.target:
        parser.error("restart-infra requires target argument")

    mgr = BrowserWorkerManager()
    action_map = {
        "start": mgr.start,
        "stop": mgr.stop,
        "restart": mgr.restart,
        "status": mgr.status,
        "restart-api": lambda: mgr.restart_api(public=args.public),
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
    main()
