"""Frontend restart/status actions for browser workers."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil

from scripts.services.browser_worker_runtime.runtime import GREEN, PROJECT_ROOT, RED, RESET, YELLOW, cprint
from scripts.services.service_utils import sync_frontend_pid_file


def _manager():
    from scripts.services.browser_worker_runtime import manager as manager_mod

    return manager_mod


def _frontend_mode(manager, public: bool) -> tuple[str, int, int, Path, Path]:
    if public:
        mode_label = "PUBLIC PREVIEW"
        api_port = 8000
        frontend_port = 6100
        pid_file = manager.pid_dir / "frontend.pid"
        log_dir = PROJECT_ROOT / "logs"
    else:
        mode_label = "ADMIN DEV"
        api_port = manager.api_port
        frontend_port = manager.frontend_port
        pid_file = manager.pid_dir / f"frontend{manager.pid_suffix}.pid"
        log_dir = PROJECT_ROOT / "logs" / "admin"
    log_dir.mkdir(parents=True, exist_ok=True)
    return mode_label, api_port, frontend_port, pid_file, log_dir


def _acquire_frontend_restart_lock(manager, wait_seconds: int = 10) -> int | None:
    deadline = time.time() + max(wait_seconds, 1)
    while time.time() <= deadline:
        try:
            fd = os.open(str(manager.frontend_restart_lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
            return fd
        except FileExistsError:
            mgr = _manager()
            stale_pid = mgr.read_pid_file(manager.frontend_restart_lock)
            if stale_pid and not mgr.is_process_alive(stale_pid):
                mgr.remove_pid_file(manager.frontend_restart_lock)
                continue
            time.sleep(0.5)
        except Exception:
            return None
    return None


def _release_frontend_restart_lock(manager, lock_fd: int | None) -> None:
    if lock_fd is not None:
        try:
            os.close(lock_fd)
        except Exception:
            pass
    _manager().remove_pid_file(manager.frontend_restart_lock)


def _cleanup_frontend_runtime(manager, frontend_port: int, pid_file: Path) -> None:
    mgr = _manager()
    pid = mgr.read_pid_file(pid_file)
    if pid and mgr.is_process_alive(pid):
        cprint(f"Stopping frontend process (PID: {pid})...")
        mgr.kill_pid(pid)
    mgr.remove_pid_file(pid_file)

    for pid_on_port in mgr.find_pids_on_port(frontend_port):
        cprint(f"Killing process on port {frontend_port} (PID: {pid_on_port})...")
        mgr.kill_pid(pid_on_port)

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["name"] != "node.exe":
                continue
            cmdline = " ".join(proc.info.get("cmdline") or [])
            has_target_port = f"--port {frontend_port}" in cmdline
            has_frontend_server = "vite" in cmdline or "preview" in cmdline
            if has_target_port and has_frontend_server:
                cprint(f"Killing orphan frontend process (PID: {proc.pid})...")
                mgr.kill_pid(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def _prepare_frontend_env(manager, api_port: int, public: bool) -> None:
    if public:
        env_local = manager.frontend_dir / ".env.local"
        if env_local.exists():
            env_local.unlink()
        return

    env_file = manager.frontend_dir / ".env.development.local"
    env_file.write_text(f"VITE_API_PORT={api_port}\n", encoding="utf-8")
    build_dir = manager.frontend_dir / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)
        cprint("Cleaned up stale build directory")


def _run_frontend_build_if_needed(manager, public: bool) -> bool:
    if not public:
        return True

    cprint("Building frontend for PUBLIC PREVIEW...", YELLOW)
    build_result = subprocess.run(
        ["npm.cmd", "run", "build"],
        cwd=str(manager.frontend_dir),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if build_result.returncode == 0:
        cprint("Frontend build completed", GREEN)
        return True

    err_msg = (build_result.stderr or build_result.stdout or "").strip()
    short_err = err_msg[-500:] if err_msg else "(no output)"
    cprint(f"Frontend build failed (rc={build_result.returncode}): {short_err}", RED)

    if not (manager.frontend_dir / "build").exists():
        cprint("No previous build found — Frontend unavailable, API-only mode", RED)
        return False

    cprint("Using previous build for preview", YELLOW)
    return True


def _read_log_tail(log_path: Path, max_chars: int = 4000) -> str:
    if not log_path.exists():
        return ""
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return content[-max_chars:]


def _has_port_collision_error(manager, stderr_log_path: Path, frontend_port: int) -> bool:
    tail = _read_log_tail(stderr_log_path)
    return f"Port {frontend_port} is already in use" in tail


def restart_frontend(manager, public: bool = False) -> bool:
    mgr = _manager()
    mode_label, api_port, frontend_port, pid_file, log_dir = _frontend_mode(manager, public)
    print(f"\n{YELLOW}{'=' * 40}")
    print(f"  Restarting {mode_label} Frontend")
    print(f"  (port {frontend_port}){RESET}")
    print(f"{YELLOW}{'=' * 40}{RESET}\n")

    lock_fd = manager._acquire_frontend_restart_lock(wait_seconds=10)
    if lock_fd is None:
        cprint("Frontend restart lock is busy; another restart is in progress", RED)
        return False

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    stdout_log_path = log_dir / f"frontend_{timestamp}.log"
    stderr_log_path = log_dir / f"frontend_err_{timestamp}.log"
    old_listener_pid = mgr.pick_listener_pid(frontend_port)
    if old_listener_pid:
        cprint(f"Pre-restart listener PID on :{frontend_port} = {old_listener_pid}", YELLOW)

    try:
        manager._cleanup_frontend_runtime(frontend_port, pid_file)
        time.sleep(2)
        manager._prepare_frontend_env(api_port=api_port, public=public)

        if not manager._run_frontend_build_if_needed(public=public):
            return False

        start_cmd = (
            ["npm.cmd", "run", "preview", "--", "--host", "--port", str(frontend_port)]
            if public
            else ["npm.cmd", "run", "dev", "--", "--host", "--port", str(frontend_port)]
        )
        cprint(f"Starting frontend ({' '.join(start_cmd)})...")

        with open(stdout_log_path, "w", encoding="utf-8") as stdout_log, open(
            stderr_log_path, "w", encoding="utf-8"
        ) as stderr_log:
            proc = mgr.tracked_popen_sync(
                start_cmd,
                role="frontend",
                cwd=str(manager.frontend_dir),
                stdout=stdout_log,
                stderr=stderr_log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        cprint(f"Frontend launcher started (PID: {proc.pid})", GREEN)

        cprint("Waiting 5s for frontend to initialize...")
        time.sleep(5)

        new_listener_pid = sync_frontend_pid_file(
            pid_file,
            frontend_port,
            proc.pid if mgr.is_process_alive(proc.pid) else None,
            listener_pid_resolver=mgr.pick_listener_pid,
            writer=mgr.write_pid_file,
            remover=mgr.remove_pid_file,
        )

        if manager._has_port_collision_error(stderr_log_path, frontend_port):
            cprint(
                f"Port collision detected in {stderr_log_path.name}: Port {frontend_port} is already in use",
                RED,
            )
            return False

        if old_listener_pid is not None and new_listener_pid == old_listener_pid:
            cprint(f"Listener PID unchanged after restart (PID: {new_listener_pid})", RED)
            return False

        url = f"http://localhost:{frontend_port}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    cprint(
                        f"Frontend healthy (mode={mode_label}, listener_pid={new_listener_pid}, url={url})",
                        GREEN,
                    )
                    return True
        except Exception as e:
            cprint(f"Frontend not responding yet (may still be starting): {e}", YELLOW)
            return False

        cprint("Frontend health check returned unexpected status", YELLOW)
        return False
    finally:
        manager._release_frontend_restart_lock(lock_fd)


def _print_frontend_status(manager, public: bool = False):
    mgr = _manager()
    mode_label, _api_port, frontend_port, frontend_pid_file, _log_dir = _frontend_mode(manager, public)
    pid = mgr.read_pid_file(frontend_pid_file)
    port_up = mgr.is_port_listening(frontend_port)
    if pid and mgr.is_process_alive(pid) and port_up:
        print(f"  {GREEN}[+] Frontend {mode_label} :{frontend_port} (PID: {pid}){RESET}")
        return

    if port_up:
        listener_pid = mgr.pick_listener_pid(frontend_port)
        if listener_pid is not None:
            mgr.write_pid_file(frontend_pid_file, listener_pid)
            print(
                f"  {YELLOW}[~] Frontend {mode_label} :{frontend_port} "
                f"(PID file stale -> auto-healed to PID {listener_pid}){RESET}"
            )
        else:
            print(f"  {YELLOW}[~] Frontend {mode_label} :{frontend_port} (port listening, PID file stale){RESET}")
        return

    print(f"  {YELLOW}[-] Frontend {mode_label} :{frontend_port}: Not running{RESET}")
