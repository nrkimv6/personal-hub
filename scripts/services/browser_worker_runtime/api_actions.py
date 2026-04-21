"""API and WMI restart actions for browser workers."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request

from app.core.runtime_fingerprint import build_runtime_fingerprint_snapshot
from scripts.services.browser_worker_runtime.runtime import GRAY, GREEN, RED, RESET, YELLOW, cprint


def _manager():
    from scripts.services.browser_worker_runtime import manager as manager_mod

    return manager_mod


def _check_wmi_health(manager) -> bool:
    try:
        result = subprocess.run(
            ["python", "-c", "import platform; platform.machine()"],
            timeout=5,
            capture_output=True,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def _fix_wmi(manager) -> bool:
    try:
        result = subprocess.run(
            ["powershell", "-Command", "Restart-Service winmgmt -Force"],
            timeout=15,
            capture_output=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _nssm_restart_elevated(manager, service_name: str) -> bool:
    ps_cmd = (
        f"$svc = Get-Service -Name {service_name!r}; "
        f"if ($svc.Status -ne 'Running') {{ Start-Service -Name {service_name!r} }} else {{ Restart-Service -Name {service_name!r} -Force }}"
    )
    try:
        result = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def _manager_app_mode(manager) -> str:
    return getattr(manager, "app_mode", "admin" if getattr(manager, "pid_suffix", "") == "_admin" else "public")


def _fetch_json(url: str, timeout: int = 3) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            payload = resp.read().decode("utf-8")
            if not payload:
                return {}
            return json.loads(payload)
    except Exception:
        return None


def restart_api(manager):
    mgr = _manager()
    print(f"\n{YELLOW}{'=' * 40}")
    print(f"  Restarting API")
    print(f"{'=' * 40}{RESET}\n")

    if not manager._check_wmi_health():
        cprint("WMI not healthy, attempting fix...", YELLOW)
        if manager._fix_wmi():
            time.sleep(5)
            if manager._check_wmi_health():
                cprint("WMI recovered successfully.", GREEN)
            else:
                cprint("WMI still unresponsive after restart. Proceeding anyway.", YELLOW)
        else:
            cprint("Failed to restart winmgmt (may need admin rights). Proceeding anyway.", YELLOW)
    else:
        cprint("WMI OK", GREEN)

    app_mode = _manager_app_mode(manager)
    expected_snapshot = build_runtime_fingerprint_snapshot(app_mode=app_mode)
    expected_fingerprint = str(expected_snapshot["runtime_fingerprint"])
    expected_source_fingerprint = str(expected_snapshot.get("source_fingerprint", ""))
    cprint(
        f"API restart target: port={manager.api_port} app_mode={app_mode} "
        f"expected_fp={expected_fingerprint[:12]}...",
        GRAY,
    )

    url = f"http://localhost:{manager.api_port}/api/v1/system/self-restart?delay=2&reason=browser_workers_py"
    killed = False
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                cprint("Self-restart API called (graceful shutdown)", GREEN)
                killed = True
    except Exception as e:
        cprint(f"Self-restart API unavailable: {e}", YELLOW)

        pids = mgr.find_pids_on_port(manager.api_port)
        if pids:
            cprint(f"API port {manager.api_port} live pids: {pids}", GRAY)
            for pid in pids:
                cprint(f"Killing API process (PID: {pid})...")
                mgr.kill_pid(pid)
            cprint("API process stopped. NSSM will auto-restart.", YELLOW)
            killed = True
        else:
            cprint(f"No process found on port {manager.api_port}", YELLOW)
            service_name = "MonitorPage-Admin" if manager.pid_suffix == "_admin" else "MonitorPage-Public"
            api_pid_file = manager.pid_dir / f"api{manager.pid_suffix}.pid"
            stale_pid = mgr.read_pid_file(api_pid_file)
            if stale_pid and mgr.is_process_alive(stale_pid):
                cprint(
                    f"Service runner alive (PID: {stale_pid}) but API port dead; "
                    f"restarting {service_name}",
                    YELLOW,
                )
                killed = manager._nssm_restart_elevated(service_name)
            elif stale_pid:
                cprint(
                    f"Stale PID file for {service_name} (PID: {stale_pid}, already dead)",
                    YELLOW,
                )
                mgr.remove_pid_file(api_pid_file)
                killed = manager._nssm_restart_elevated(service_name)

    if killed:
        cprint("Waiting for NSSM to restart API (up to 60s)...")
        healthy = False
        fingerprint_url = f"http://localhost:{manager.api_port}/api/v1/system/runtime-fingerprint"
        status_url = f"http://localhost:{manager.api_port}/api/v1/system/status"
        for i in range(12):
            time.sleep(5)
            fingerprint_data = _fetch_json(fingerprint_url, timeout=3)
            if fingerprint_data is not None:
                actual_fingerprint = str(fingerprint_data.get("runtime_fingerprint", ""))
                actual_source_fingerprint = str(fingerprint_data.get("source_fingerprint", ""))
                actual_app_mode = str(fingerprint_data.get("app_mode", ""))
                if actual_fingerprint == expected_fingerprint:
                    cprint(f"API runtime fingerprint matched (took ~{(i + 1) * 5}s)", GREEN)
                    healthy = True
                    break
                if (
                    actual_source_fingerprint
                    and actual_source_fingerprint == expected_source_fingerprint
                    and actual_app_mode == app_mode
                ):
                    cprint(
                        f"API source fingerprint matched (runtime drift allowed, took ~{(i + 1) * 5}s)",
                        GREEN,
                    )
                    healthy = True
                    break
                cprint(
                    "Runtime fingerprint mismatch: "
                    f"expected={expected_fingerprint[:12]}... actual={actual_fingerprint[:12]}...",
                    YELLOW,
                )
                continue
            try:
                with urllib.request.urlopen(status_url, timeout=3) as resp:
                    if resp.status == 200:
                        cprint(f"API server is healthy (legacy /system/status fallback, took ~{(i + 1) * 5}s)", GREEN)
                        healthy = True
                        break
            except Exception:
                pass
        if not healthy:
            cprint("API not responding after 60s - check NSSM service status", RED)
    else:
        cprint("No API process found to restart. Check NSSM service 'MonitorPage-Admin'.", RED)
