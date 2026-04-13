"""API and WMI restart actions for browser workers."""

from __future__ import annotations

import subprocess
import time
import urllib.request

from scripts.services.browser_worker_runtime.runtime import GREEN, RED, RESET, YELLOW, cprint


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
                cprint(f"Service runner alive (PID: {stale_pid}) but API port dead", YELLOW)
                killed = manager._nssm_restart_elevated(service_name)
            elif stale_pid:
                cprint(f"Stale PID file (PID: {stale_pid}, already dead)", YELLOW)
                mgr.remove_pid_file(api_pid_file)
                killed = manager._nssm_restart_elevated(service_name)

    if killed:
        cprint("Waiting for NSSM to restart API (up to 60s)...")
        healthy = False
        for i in range(12):
            time.sleep(5)
            try:
                with urllib.request.urlopen(
                    f"http://localhost:{manager.api_port}/api/v1/system/status", timeout=3
                ) as resp:
                    if resp.status == 200:
                        cprint(f"API server is healthy (took ~{(i + 1) * 5}s)", GREEN)
                        healthy = True
                        break
            except Exception:
                pass
        if not healthy:
            cprint("API not responding after 60s - check NSSM service status", RED)
    else:
        cprint("No API process found to restart. Check NSSM service 'MonitorPage-Admin'.", RED)
