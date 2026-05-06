"""Frontend restart/status actions for browser workers."""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil

from scripts.services.frontend_mode import (
    build_frontend_env,
    ensure_frontend_runtime_tsconfigs,
    describe_frontend_runtime,
    get_frontend_api_port,
    get_frontend_mode,
    get_frontend_outdir,
    write_frontend_build_log,
)
from scripts.services.service_utils import classify_frontend_failure, describe_listener, format_listener_metadata
from scripts.services.browser_worker_runtime.runtime import GREEN, PROJECT_ROOT, RED, RESET, YELLOW, cprint


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


def _cleanup_frontend_runtime(manager, frontend_port: int, pid_file: Path) -> list[int]:
    mgr = _manager()
    terminated_pids: list[int] = []

    def _record_kill(pid: int, message: str) -> None:
        if pid <= 0:
            return
        cprint(message)
        if not mgr.kill_pid(pid):
            _emit_listener_diagnostics(
                frontend_port,
                f"Failed to terminate PID {pid} while clearing port {frontend_port}",
                RED,
            )
            return
        if pid not in terminated_pids:
            terminated_pids.append(pid)

    pid = mgr.read_pid_file(pid_file)
    if pid and mgr.is_process_alive(pid):
        _record_kill(pid, f"Stopping frontend process (PID: {pid})...")
    mgr.remove_pid_file(pid_file)

    for pid_on_port in mgr.find_pids_on_port(frontend_port):
        _record_kill(pid_on_port, f"Killing process on port {frontend_port} (PID: {pid_on_port})...")

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["name"] != "node.exe":
                continue
            cmdline = " ".join(proc.info.get("cmdline") or [])
            has_target_port = f"--port {frontend_port}" in cmdline
            has_frontend_server = "vite" in cmdline or "preview" in cmdline
            if has_target_port and has_frontend_server:
                _record_kill(proc.pid, f"Killing orphan frontend process (PID: {proc.pid})...")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return terminated_pids


def _wait_for_terminated_pids(pids: object, timeout_seconds: float = 15.0) -> bool:
    mgr = _manager()
    if isinstance(pids, int):
        tracked_pids = [pids] if pids > 0 else []
    elif isinstance(pids, (list, tuple, set)):
        tracked_pids = [int(pid) for pid in pids if isinstance(pid, int) and pid > 0]
    else:
        tracked_pids = []

    if not tracked_pids:
        return True

    deadline = time.time() + max(timeout_seconds, 1.0)
    remaining = tracked_pids
    while time.time() <= deadline:
        remaining = [pid for pid in tracked_pids if mgr.is_process_alive(pid)]
        if not remaining:
            return True
        time.sleep(0.5)

    cprint(
        f"Timed out waiting for old frontend processes to exit: {', '.join(str(pid) for pid in remaining)}",
        YELLOW,
    )
    return False


def _reset_frontend_runtime_types(manager, public: bool) -> None:
    runtime_outdir = manager.frontend_dir / get_frontend_outdir(public)
    runtime_types_dir = runtime_outdir / "types"
    if not runtime_types_dir.exists():
        return

    try:
        shutil.rmtree(runtime_types_dir, ignore_errors=False)
        cprint(f"Cleared stale frontend runtime types: {runtime_types_dir}", YELLOW)
    except Exception as exc:
        cprint(f"Could not clear stale frontend runtime types ({runtime_types_dir}): {exc}", YELLOW)


def _frontend_runtime_env(manager, public: bool) -> dict[str, str]:
    api_port = None if public else manager.api_port
    return build_frontend_env(os.environ, public=public, api_port=api_port)


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


def _run_frontend_build_if_needed(
    manager,
    public: bool,
    frontend_env: dict[str, str] | None = None,
    *,
    timestamp: str | None = None,
    log_dir: Path | None = None,
) -> bool:
    if not public:
        return True

    if frontend_env is None:
        frontend_env = _frontend_runtime_env(manager, public)
    if timestamp is None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
    if log_dir is None:
        _, _, _, _, log_dir = _frontend_mode(manager, public)

    ensure_frontend_runtime_tsconfigs(manager.frontend_dir)
    cprint("Building frontend for PUBLIC PREVIEW...", YELLOW)
    build_result = subprocess.run(
        ["npm.cmd", "run", "build"],
        cwd=str(manager.frontend_dir),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=frontend_env,
    )
    if build_result.returncode == 0:
        cprint("Frontend build completed", GREEN)
        return True

    build_log_path = write_frontend_build_log(
        log_dir,
        timestamp,
        public=True,
        returncode=build_result.returncode,
        stdout=build_result.stdout or "",
        stderr=build_result.stderr or "",
    )
    failure_class = classify_frontend_failure(build_result.stdout, build_result.stderr)
    listener_metadata = describe_listener(_frontend_mode(manager, public)[2])
    rendered_listener = format_listener_metadata(listener_metadata)
    cprint(
        "Frontend build failed "
        f"(rc={build_result.returncode}, class={failure_class}, log={build_log_path}, listener={rendered_listener})",
        RED,
    )
    if failure_class == "build_lock_permission":
        cprint(
            "Build lock/permission detected; check Session 0 service ownership or elevate before retrying PUBLIC PREVIEW.",
            YELLOW,
        )

    if not (manager.frontend_dir / "build").exists():
        cprint(
            "No previous build artifact found - cannot run PUBLIC PREVIEW "
            f"(class={failure_class}, build_log={build_log_path})",
            RED,
        )
        return False

    cprint(
        "Using previous build artifact for fallback preview "
        f"(class={failure_class}, build_log={build_log_path})",
        YELLOW,
    )
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


def _emit_listener_diagnostics(frontend_port: int, reason: str, color: str = YELLOW) -> None:
    listener_metadata = describe_listener(frontend_port)
    cprint(f"{reason} ({format_listener_metadata(listener_metadata)})", color)
    if listener_metadata.get("pid") is not None:
        cprint(
            "Listener cleanup may require elevation or another session owns the port. "
            "Access denied / EPERM class failures should be treated as permission or service-lock issues.",
            YELLOW,
        )


def _wait_for_frontend_listener(frontend_port: int, launcher_pid: int, timeout_seconds: float = 15.0) -> int | None:
    mgr = _manager()
    deadline = time.time() + max(timeout_seconds, 1.0)

    while time.time() <= deadline:
        listener_pid = mgr.pick_listener_pid(frontend_port)
        if listener_pid is not None:
            return listener_pid

        if launcher_pid and not mgr.is_process_alive(launcher_pid):
            return None

        time.sleep(0.5)

    return None


def _wait_for_frontend_http_ready(url: str, launcher_pid: int, timeout_seconds: float = 15.0) -> tuple[bool, str | None]:
    mgr = _manager()
    deadline = time.time() + max(timeout_seconds, 1.0)
    last_error: str | None = None

    while time.time() <= deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    return True, None
                last_error = f"unexpected status: {resp.status}"
        except Exception as exc:
            last_error = str(exc)
            if launcher_pid and not mgr.is_process_alive(launcher_pid):
                break

        time.sleep(0.5)

    return False, last_error


def _read_frontend_mode_payload(frontend_port: int, timeout_seconds: float = 3.0) -> dict[str, object]:
    url = f"http://localhost:{frontend_port}/__local/frontend-mode"
    with urllib.request.urlopen(url, timeout=timeout_seconds) as resp:
        if resp.status != 200:
            raise RuntimeError(f"unexpected status: {resp.status}")
        raw = resp.read().decode("utf-8", errors="replace")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("frontend-mode payload is not an object")
    return payload


def _verify_frontend_runtime_readback(frontend_port: int, public: bool, api_port: int) -> tuple[bool, str]:
    expected = {
        "mode": get_frontend_mode(public),
        "outDir": get_frontend_outdir(public),
        "apiPort": get_frontend_api_port(public, api_port),
    }
    try:
        payload = _read_frontend_mode_payload(frontend_port)
    except Exception as exc:
        return False, f"read-back failed: {exc}"

    mismatches = [
        f"{key}: expected {value!r}, got {payload.get(key)!r}"
        for key, value in expected.items()
        if str(payload.get(key)) != value
    ]
    if mismatches:
        return False, "; ".join(mismatches)
    return True, (
        f"mode={payload.get('mode')} "
        f"outDir={payload.get('outDir')} "
        f"apiPort={payload.get('apiPort')}"
    )


def restart_frontend(manager, public: bool = False) -> bool:
    mgr = _manager()
    mode_label, api_port, frontend_port, pid_file, log_dir = _frontend_mode(manager, public)
    frontend_env = _frontend_runtime_env(manager, public)
    print(f"\n{YELLOW}{'=' * 40}")
    print(f"  Restarting {mode_label} Frontend")
    print(f"  (port {frontend_port}){RESET}")
    print(f"{YELLOW}{'=' * 40}{RESET}\n")
    cprint(f"Frontend runtime contract: {describe_frontend_runtime(public, api_port=api_port)}", YELLOW)
    ensure_frontend_runtime_tsconfigs(manager.frontend_dir)

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
        terminated_pids = manager._cleanup_frontend_runtime(frontend_port, pid_file)
        if not _wait_for_terminated_pids(terminated_pids):
            _emit_listener_diagnostics(frontend_port, f"Old frontend listener still present after cleanup on :{frontend_port}")
        _reset_frontend_runtime_types(manager, public)
        time.sleep(2)
        manager._prepare_frontend_env(api_port=api_port, public=public)

        if not manager._run_frontend_build_if_needed(
            public=public,
            frontend_env=frontend_env,
            timestamp=timestamp,
            log_dir=log_dir,
        ):
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
                env=frontend_env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        cprint(f"Frontend launcher started (PID: {proc.pid})", GREEN)

        cprint(f"Waiting for frontend listener on :{frontend_port}...", YELLOW)
        new_listener_pid = _wait_for_frontend_listener(frontend_port, proc.pid)
        if new_listener_pid is not None:
            mgr.write_pid_file(pid_file, new_listener_pid)
        else:
            mgr.remove_pid_file(pid_file)
            if mgr.is_process_alive(proc.pid):
                cprint(
                    "Launcher is alive but frontend listener was not detected; launcher PID will not be written",
                    YELLOW,
                )

        if manager._has_port_collision_error(stderr_log_path, frontend_port):
            _emit_listener_diagnostics(
                frontend_port,
                f"Port collision detected in {stderr_log_path.name}: Port {frontend_port} is already in use",
                RED,
            )
            return False

        url = f"http://localhost:{frontend_port}"
        healthy, last_error = _wait_for_frontend_http_ready(url, proc.pid)
        if healthy:
            runtime_ok, runtime_detail = _verify_frontend_runtime_readback(frontend_port, public, api_port)
            if not runtime_ok:
                cprint(f"Frontend runtime read-back mismatch: {runtime_detail}", RED)
                return False
            if old_listener_pid is not None and new_listener_pid == old_listener_pid:
                cprint(
                    f"Listener PID unchanged after restart (PID: {new_listener_pid}) but frontend is healthy",
                    YELLOW,
                )
            cprint(
                f"Frontend healthy (mode={mode_label}, listener_pid={new_listener_pid}, url={url}, {runtime_detail})",
                GREEN,
            )
            return True

        if old_listener_pid is not None and new_listener_pid == old_listener_pid:
            cprint(f"Listener PID unchanged after restart (PID: {new_listener_pid})", RED)
            _emit_listener_diagnostics(frontend_port, "Listener PID remained unchanged and frontend health did not recover", RED)
        elif last_error:
            cprint(f"Frontend not responding yet (may still be starting): {last_error}", YELLOW)
        else:
            cprint("Frontend not responding yet (may still be starting)", YELLOW)
        _emit_listener_diagnostics(frontend_port, "Frontend restart failed health gate", RED)
        return False
    finally:
        manager._release_frontend_restart_lock(lock_fd)


def _print_frontend_status(manager, public: bool = False):
    mgr = _manager()
    mode_label, _api_port, frontend_port, frontend_pid_file, _log_dir = _frontend_mode(manager, public)
    contract = describe_frontend_runtime(public, api_port=_api_port)
    pid = mgr.read_pid_file(frontend_pid_file)
    port_up = mgr.is_port_listening(frontend_port)
    if pid and mgr.is_process_alive(pid) and port_up:
        print(f"  {GREEN}[+] Frontend {mode_label} :{frontend_port} ({contract}, PID: {pid}){RESET}")
        return

    if port_up:
        listener_pid = mgr.pick_listener_pid(frontend_port)
        if listener_pid is not None:
            mgr.write_pid_file(frontend_pid_file, listener_pid)
            print(
                f"  {YELLOW}[~] Frontend {mode_label} :{frontend_port} ({contract}) "
                f"(PID file stale -> auto-healed to PID {listener_pid}){RESET}"
            )
        else:
            print(f"  {YELLOW}[~] Frontend {mode_label} :{frontend_port} ({contract}) (port listening, PID file stale){RESET}")
        return

    print(f"  {YELLOW}[-] Frontend {mode_label} :{frontend_port} ({contract}): Not running{RESET}")
