"""Watchdog lifecycle actions for browser workers."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from datetime import datetime

from scripts.services.browser_worker_runtime.runtime import CYAN, GRAY, GREEN, PROJECT_ROOT, RED, RESET, YELLOW, cprint, _kill_by_cmdline


def _manager():
    from scripts.services.browser_worker_runtime import manager as manager_mod

    return manager_mod


def start(manager):
    mgr = _manager()
    print(f"\n{CYAN}{'=' * 40}")
    print(f"  Starting Browser Workers")
    print(f"  (WorkerOrchestrator Architecture){RESET}")
    print(f"{CYAN}{'=' * 40}{RESET}\n")

    if mgr.is_port_listening(manager.api_port):
        pids = mgr.find_pids_on_port(manager.api_port)
        if pids:
            cprint(f"Port {manager.api_port} in use (PIDs: {pids})", GRAY)

    manager._cleanup_legacy()
    started = 0

    for w in manager.workers:
        pid_path = manager.pid_dir / w["pid_file"]
        pid = mgr.read_pid_file(pid_path)
        if pid and mgr.is_process_alive(pid):
            cprint(f"{w['name']}: already running (PID: {pid})", YELLOW)
            continue

        if str(manager.python_exe) in " ".join(w["cmd"]) and not manager.python_exe.exists():
            cprint(f"{w['name']}: Python venv not found, skipping", RED)
            continue

        cprint(f"Starting {w['name']}...")
        env = {**os.environ, **w["env"]}

        stderr_file = None
        if w["name"] == "Dev Runner Command Listener":
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            stderr_log_path = PROJECT_ROOT / "logs" / "admin" / f"dev_runner_stderr_{ts}.log"
            stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_file = open(str(stderr_log_path), "w", encoding="utf-8")

        proc = mgr.tracked_popen_sync(
            w["cmd"],
            role=w.get("role", "watchdog"),
            cwd=str(PROJECT_ROOT),
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stderr=stderr_file,
        )
        mgr.write_pid_file(pid_path, proc.pid)
        cprint(f"{w['name']} started (PID: {proc.pid})", GREEN)

        if w["name"] == "Dev Runner Command Listener":
            time.sleep(0.5)
            if not mgr.is_process_alive(proc.pid):
                stderr_file.flush()
                stderr_content = stderr_log_path.read_text(encoding="utf-8", errors="replace") if stderr_log_path.exists() else ""
                cprint(f"{w['name']}: process died immediately — check {stderr_log_path.name}", RED)
                if stderr_content.strip():
                    cprint(f"  stderr: {stderr_content[:300]}", RED)

        started += 1

    if started > 0:
        cprint(f"{started} watchdog(s) started", GREEN)
    else:
        cprint("All watchdogs already running", YELLOW)


def stop(manager):
    print(f"\n{RED}{'=' * 40}")
    print(f"  Stopping Browser Workers")
    print(f"{'=' * 40}{RESET}\n")

    stopped = 0

    for w in manager.workers:
        pid_path = manager.pid_dir / w["pid_file"]
        pid = _manager().read_pid_file(pid_path)
        if pid and _manager().is_process_alive(pid):
            cprint(f"Stopping {w['name']} (PID: {pid})...")
            try:
                from app.shared.process.registry import ProcessRegistry

                asyncio.run(ProcessRegistry().unregister(pid))
            except Exception:
                pass
            _manager().kill_pid(pid)
            cprint(f"{w['name']} stopped", GREEN)
            stopped += 1
        _manager().remove_pid_file(pid_path)

    for pf in manager.worker_pid_files:
        pid_path = manager.pid_dir / pf
        pid = _manager().read_pid_file(pid_path)
        if pid and _manager().is_process_alive(pid):
            cprint(f"Stopping worker process (PID: {pid})...")
            try:
                from app.shared.process.registry import ProcessRegistry

                asyncio.run(ProcessRegistry().unregister(pid))
            except Exception:
                pass
            _manager().kill_pid(pid)
            stopped += 1
        _manager().remove_pid_file(pid_path)

    manager._cleanup_legacy()

    leaked = _kill_by_cmdline("dev-runner-command-listener")
    if leaked:
        cprint(f"잔류 프로세스 {leaked}개 정리됨 (PID 파일 누락)", YELLOW)

    if stopped > 0 or leaked > 0:
        cprint(f"{stopped + leaked} process(es) stopped", GREEN)
    else:
        cprint("No watchdogs were running", YELLOW)


def restart(manager):
    manager.stop()
    time.sleep(2)
    manager.start()


def _cleanup_legacy(manager):
    mgr = _manager()
    for pf in manager.legacy_pid_files:
        pid_path = manager.pid_dir / pf
        pid = mgr.read_pid_file(pid_path)
        if pid and mgr.is_process_alive(pid):
            cprint(f"Stopping legacy process (PID: {pid}) from {pf}", YELLOW)
            mgr.kill_pid(pid)
        mgr.remove_pid_file(pid_path)
