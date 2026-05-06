"""API and WMI restart actions for browser workers."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.core.runtime_fingerprint import build_runtime_fingerprint_snapshot
from scripts.services.browser_worker_runtime.runtime import GRAY, GREEN, RED, RESET, YELLOW, cprint
from scripts.services.service_utils import find_pids_on_port, is_process_alive, read_pid_file


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


READINESS_PROBE_HOSTS = ("127.0.0.1", "localhost")
READINESS_TIMEOUT_SECONDS = 60
READINESS_POLL_SECONDS = 5


@dataclass(frozen=True)
class HttpProbeResult:
    data: dict[str, object] | None
    url: str | None
    fallback_used: bool = False
    last_error: str | None = None


@dataclass(frozen=True)
class RestartApiReadinessResult:
    healthy: bool
    reason: str
    elapsed_seconds: int
    hard_failure: bool = False
    url: str | None = None
    last_error: str | None = None
    evidence: str | None = None


def _api_probe_url(api_port: int, host: str, path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    return f"http://{host}:{api_port}{path}"


def _fetch_json_with_host_fallback(api_port: int, path: str, timeout: int = 3) -> HttpProbeResult:
    errors: list[str] = []
    for index, host in enumerate(READINESS_PROBE_HOSTS):
        url = _api_probe_url(api_port, host, path)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                if resp.status != 200:
                    errors.append(f"{url} -> HTTP {resp.status}")
                    continue
                payload = resp.read().decode("utf-8")
                return HttpProbeResult(
                    data=json.loads(payload) if payload else {},
                    url=url,
                    fallback_used=index > 0,
                )
        except Exception as exc:
            errors.append(f"{url} -> {type(exc).__name__}: {exc}")
    return HttpProbeResult(data=None, url=None, last_error="; ".join(errors[-2:]) or None)


def _service_log_candidates(manager, target: "RestartApiTarget") -> list[Path]:
    log_dir = Path(getattr(manager, "log_dir", Path("logs") / "admin"))
    candidates = [
        log_dir / f"service_{target.service_name}.log",
        *(log_dir.glob("service_runner_*.log") if log_dir.exists() else []),
    ]
    return sorted(
        [path for path in candidates if path.exists()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _tail_text(path: Path, max_bytes: int = 65536) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _classify_restart_api_timeout(
    manager,
    target: "RestartApiTarget",
    *,
    elapsed_seconds: int,
    last_error: str | None,
) -> RestartApiReadinessResult:
    for log_path in _service_log_candidates(manager, target):
        tail = _tail_text(log_path)
        if not tail:
            continue
        last_start = tail.rfind("Monitor Page Service Starting")
        scope = tail[last_start:] if last_start >= 0 else tail
        if "Service failed:" in scope or "Traceback (most recent call last)" in scope:
            return RestartApiReadinessResult(
                healthy=False,
                reason="startup_exception",
                elapsed_seconds=elapsed_seconds,
                hard_failure=True,
                last_error=last_error,
                evidence=str(log_path),
            )

        importing_at = scope.rfind("Importing app.main...")
        imported_at = scope.rfind("app.main imported")
        api_starting_at = scope.rfind("API Server starting on port")
        if importing_at >= 0 and importing_at > max(imported_at, api_starting_at):
            return RestartApiReadinessResult(
                healthy=False,
                reason="cold_import_in_progress",
                elapsed_seconds=elapsed_seconds,
                hard_failure=False,
                last_error=last_error,
                evidence=str(log_path),
            )

    find_pids = getattr(manager, "find_pids_on_port", find_pids_on_port)
    pids = find_pids(target.api_port)
    if pids:
        return RestartApiReadinessResult(
            healthy=False,
            reason="port_listening_probe_failed",
            elapsed_seconds=elapsed_seconds,
            hard_failure=True,
            last_error=last_error,
            evidence=f"port_pids={pids}",
        )

    read_pid = getattr(manager, "read_pid_file", read_pid_file)
    process_alive = getattr(manager, "is_process_alive", is_process_alive)
    stale_pid = read_pid(target.pid_file)
    if stale_pid and process_alive(stale_pid):
        return RestartApiReadinessResult(
            healthy=False,
            reason="runner_alive_not_ready",
            elapsed_seconds=elapsed_seconds,
            hard_failure=False,
            last_error=last_error,
            evidence=f"pid={stale_pid}",
        )

    return RestartApiReadinessResult(
        healthy=False,
        reason="service_not_running",
        elapsed_seconds=elapsed_seconds,
        hard_failure=True,
        last_error=last_error,
    )


def _wait_for_restart_api_readiness(
    manager,
    target: "RestartApiTarget",
    *,
    expected_fingerprint: str,
    expected_source_fingerprint: str,
    timeout_seconds: int = READINESS_TIMEOUT_SECONDS,
    poll_seconds: int = READINESS_POLL_SECONDS,
) -> RestartApiReadinessResult:
    deadline = time.monotonic() + timeout_seconds
    elapsed = 0
    last_error: str | None = None
    while time.monotonic() < deadline:
        time.sleep(poll_seconds)
        elapsed = min(timeout_seconds, elapsed + poll_seconds)

        fingerprint_probe = _fetch_json_with_host_fallback(
            target.api_port,
            "/api/v1/system/runtime-fingerprint",
            timeout=3,
        )
        if fingerprint_probe.fallback_used and fingerprint_probe.url:
            cprint(f"127.0.0.1 probe failed; using fallback {fingerprint_probe.url}", YELLOW)
        if fingerprint_probe.data is not None:
            actual_fingerprint = str(fingerprint_probe.data.get("runtime_fingerprint", ""))
            actual_source_fingerprint = str(fingerprint_probe.data.get("source_fingerprint", ""))
            actual_app_mode = str(fingerprint_probe.data.get("app_mode", ""))
            if actual_fingerprint == expected_fingerprint:
                return RestartApiReadinessResult(
                    healthy=True,
                    reason="runtime_fingerprint_matched",
                    elapsed_seconds=elapsed,
                    url=fingerprint_probe.url,
                )
            if (
                actual_source_fingerprint
                and actual_source_fingerprint == expected_source_fingerprint
                and actual_app_mode == target.app_mode
            ):
                return RestartApiReadinessResult(
                    healthy=True,
                    reason="source_fingerprint_matched",
                    elapsed_seconds=elapsed,
                    url=fingerprint_probe.url,
                )
            cprint(
                "Runtime fingerprint mismatch: "
                f"expected={expected_fingerprint[:12]}... actual={actual_fingerprint[:12]}...",
                YELLOW,
            )
            continue
        last_error = fingerprint_probe.last_error

        liveness_probe = _fetch_json_with_host_fallback(
            target.api_port,
            "/api/v1/system/liveness",
            timeout=3,
        )
        if liveness_probe.fallback_used and liveness_probe.url:
            cprint(f"127.0.0.1 probe failed; using fallback {liveness_probe.url}", YELLOW)
        if liveness_probe.data is not None:
            return RestartApiReadinessResult(
                healthy=True,
                reason="liveness_fallback_200",
                elapsed_seconds=elapsed,
                url=liveness_probe.url,
            )
        last_error = liveness_probe.last_error or last_error

        status_probe = _fetch_json_with_host_fallback(
            target.api_port,
            "/api/v1/system/status",
            timeout=3,
        )
        if status_probe.fallback_used and status_probe.url:
            cprint(f"127.0.0.1 probe failed; using fallback {status_probe.url}", YELLOW)
        if status_probe.data is not None:
            return RestartApiReadinessResult(
                healthy=True,
                reason="status_fallback_200",
                elapsed_seconds=elapsed,
                url=status_probe.url,
            )
        last_error = status_probe.last_error or last_error

    return _classify_restart_api_timeout(
        manager,
        target,
        elapsed_seconds=timeout_seconds,
        last_error=last_error,
    )


def _frontend_port_for_api_port(api_port: int) -> int | None:
    if api_port == 8001:
        return 6101
    if api_port == 8000:
        return 6100
    return None


@dataclass(frozen=True)
class RestartApiTarget:
    api_port: int
    app_mode: str
    pid_suffix: str
    pid_file: Path
    service_name: str


def _restart_api_target(manager, public: bool) -> RestartApiTarget:
    if public:
        return RestartApiTarget(
            api_port=8000,
            app_mode="public",
            pid_suffix="",
            pid_file=manager.pid_dir / "api.pid",
            service_name="MonitorPage-Public",
        )

    pid_suffix = getattr(manager, "pid_suffix", "_admin")
    app_mode = _manager_app_mode(manager)
    return RestartApiTarget(
        api_port=getattr(manager, "api_port", 8001),
        app_mode=app_mode,
        pid_suffix=pid_suffix,
        pid_file=manager.pid_dir / f"api{pid_suffix}.pid",
        service_name="MonitorPage-Admin" if pid_suffix == "_admin" else "MonitorPage-Public",
    )


def _close_api_gate(api_port: int) -> None:
    frontend_port = _frontend_port_for_api_port(api_port)
    if frontend_port is None:
        cprint(f"API gate close skipped: unsupported API port {api_port}", YELLOW)
        return

    url = f"http://127.0.0.1:{frontend_port}/__local/api-gate/close"
    payload = json.dumps(
        {"api_port": api_port, "reason": "browser_workers restart-api"}
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                cprint("API gate closed before restart", GREEN)
            else:
                cprint(f"API gate close returned HTTP {resp.status}; restart continues", YELLOW)
    except Exception as exc:
        cprint(f"API gate close failed, restart continues: {exc}", YELLOW)


def restart_api(manager, public: bool = False) -> bool:
    mgr = _manager()
    target = _restart_api_target(manager, public)
    print(f"\n{YELLOW}{'=' * 40}")
    print(f"  Restarting {'PUBLIC ' if public else ''}API")
    print(f"{'=' * 40}{RESET}\n")

    _close_api_gate(target.api_port)

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

    expected_snapshot = build_runtime_fingerprint_snapshot(app_mode=target.app_mode)
    expected_fingerprint = str(expected_snapshot["runtime_fingerprint"])
    expected_source_fingerprint = str(expected_snapshot.get("source_fingerprint", ""))
    cprint(
        f"API restart target: port={target.api_port} app_mode={target.app_mode} "
        f"expected_fp={expected_fingerprint[:12]}...",
        GRAY,
    )

    url = f"http://127.0.0.1:{target.api_port}/api/v1/system/self-restart?delay=2&reason=browser_workers_py"
    killed = False
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                cprint("Self-restart API called (graceful shutdown)", GREEN)
                killed = True
    except Exception as e:
        cprint(f"Self-restart API unavailable: {e}", YELLOW)

        pids = mgr.find_pids_on_port(target.api_port)
        if pids:
            cprint(f"API port {target.api_port} live pids: {pids}", GRAY)
            for pid in pids:
                cprint(f"Killing API process (PID: {pid})...")
                mgr.kill_pid(pid)
            cprint("API process stopped. NSSM will auto-restart.", YELLOW)
            killed = True
        else:
            cprint(f"No process found on port {target.api_port}", YELLOW)
            stale_pid = mgr.read_pid_file(target.pid_file)
            if stale_pid and mgr.is_process_alive(stale_pid):
                cprint(
                    f"Service runner alive (PID: {stale_pid}) but API port dead; "
                    f"restarting {target.service_name}",
                    YELLOW,
                )
                killed = manager._nssm_restart_elevated(target.service_name)
            elif stale_pid:
                cprint(
                    f"Stale PID file for {target.service_name} (PID: {stale_pid}, already dead)",
                    YELLOW,
                )
                mgr.remove_pid_file(target.pid_file)
                killed = manager._nssm_restart_elevated(target.service_name)

    if killed:
        cprint("Waiting for NSSM to restart API (up to 60s)...")
        readiness = _wait_for_restart_api_readiness(
            manager,
            target,
            expected_fingerprint=expected_fingerprint,
            expected_source_fingerprint=expected_source_fingerprint,
        )
        if readiness.healthy:
            if readiness.reason == "runtime_fingerprint_matched":
                cprint(f"API runtime fingerprint matched (took ~{readiness.elapsed_seconds}s)", GREEN)
            elif readiness.reason == "source_fingerprint_matched":
                cprint(
                    f"API source fingerprint matched (runtime drift allowed, took ~{readiness.elapsed_seconds}s)",
                    GREEN,
                )
            else:
                cprint(
                    f"API server is healthy ({readiness.reason}, took ~{readiness.elapsed_seconds}s, url={readiness.url})",
                    GREEN,
                )
            return True

        message = (
            f"API readiness timeout after {readiness.elapsed_seconds}s "
            f"(reason={readiness.reason}"
        )
        if readiness.evidence:
            message += f", evidence={readiness.evidence}"
        if readiness.last_error:
            message += f", last_error={readiness.last_error}"
        message += ")"
        if readiness.hard_failure:
            cprint(message, RED)
            return False
        cprint(f"{message}; service may still be starting after slow import", YELLOW)
        return True
    else:
        cprint(f"No API process found to restart. Check NSSM service '{target.service_name}'.", RED)
        return False
