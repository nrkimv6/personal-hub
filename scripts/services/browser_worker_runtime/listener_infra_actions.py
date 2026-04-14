"""Listener and infra restart actions for browser workers."""

from __future__ import annotations

import os
import subprocess
import time

from scripts.services.browser_worker_runtime.runtime import CYAN, GREEN, PROJECT_ROOT, RED, RESET, YELLOW, cprint


def _manager():
    from scripts.services.browser_worker_runtime import manager as manager_mod

    return manager_mod


def restart_listener(manager):
    mgr = _manager()
    print(f"\n{CYAN}{'=' * 40}")
    print(f"  Restarting Command Listener")
    print(f"{'=' * 40}{RESET}\n")

    listener_pids = [
        manager.pid_dir / f"command_listener_watchdog{manager.pid_suffix}.pid",
        manager.pid_dir / f"command_listener{manager.pid_suffix}.pid",
        manager.pid_dir / f"dev_runner_watchdog{manager.pid_suffix}.pid",
        manager.pid_dir / f"dev_runner_command_listener{manager.pid_suffix}.pid",
    ]
    for pid_path in listener_pids:
        pid = mgr.read_pid_file(pid_path)
        if pid and mgr.is_process_alive(pid):
            cprint(f"Stopping {pid_path.name} (PID: {pid})...", YELLOW)
            mgr.kill_pid(pid)
        mgr.remove_pid_file(pid_path)

    time.sleep(1)

    for w in manager.workers:
        if w["role"] not in ("listener", "dev_listener"):
            continue
        pid_path = manager.pid_dir / w["pid_file"]
        pid = mgr.read_pid_file(pid_path)
        if pid and mgr.is_process_alive(pid):
            cprint(f"{w['name']}: already running (PID: {pid})", YELLOW)
            continue
        cprint(f"Starting {w['name']}...")
        env = {**os.environ, **w["env"]}
        proc = mgr.tracked_popen_sync(
            w["cmd"],
            role=w.get("role", "watchdog"),
                cwd=str(PROJECT_ROOT),
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        mgr.write_pid_file(pid_path, proc.pid)
        cprint(f"{w['name']} started (PID: {proc.pid})", GREEN)


def restart_infra(manager, target: str):
    mgr = _manager()
    print(f"\n{CYAN}{'=' * 40}")
    print(f"  Restarting Infra: {target}")
    print(f"{'=' * 40}{RESET}\n")

    try:
        from app.modules.system.config import MANAGED_PROJECTS

        proj = MANAGED_PROJECTS.get("monitor-page", {})
        workers_cfg = proj.get("workers", {}).get("items", [])
        infra_items = [w for w in workers_cfg if w.get("tier") == "infra" and w["name"] == target]
    except Exception as e:
        cprint(f"config 로드 실패: {e}", RED)
        return

    if not infra_items:
        cprint(f"infra 항목 없음: {target}", RED)
        return

    item = infra_items[0]
    pid_dir = PROJECT_ROOT / proj["workers"]["pid_dir"]

    for pid_key in ("watchdog_pid_file", "worker_pid_file"):
        pf = item.get(pid_key)
        if not pf:
            continue
        pid_path = pid_dir / pf
        pid = mgr.read_pid_file(pid_path)
        if pid and mgr.is_process_alive(pid):
            cprint(f"Stopping {pf} (PID: {pid})...", YELLOW)
            mgr.kill_pid(pid)
        mgr.remove_pid_file(pid_path)

    time.sleep(1)

    for w in manager.workers:
        wdog_pf = item.get("watchdog_pid_file")
        if not wdog_pf or w["pid_file"] != wdog_pf:
            continue
        pid_path = manager.pid_dir / w["pid_file"]
        cprint(f"Starting {w['name']}...")
        env = {**os.environ, **w["env"]}
        proc = mgr.tracked_popen_sync(
            w["cmd"],
            role=w.get("role", "watchdog"),
            cwd=str(PROJECT_ROOT),
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        mgr.write_pid_file(pid_path, proc.pid)
        cprint(f"{w['name']} started (PID: {proc.pid})", GREEN)
        break
