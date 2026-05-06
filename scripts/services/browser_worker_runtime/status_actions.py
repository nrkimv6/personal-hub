"""Status and Redis actions for browser workers."""

from __future__ import annotations

from datetime import datetime, timezone
import subprocess
import time
import json

from app.core.runtime_fingerprint import get_worker_runtime_fingerprint_snapshot
from app.shared.process.subprocess_text import with_text_subprocess_defaults
from scripts.services.browser_worker_runtime.runtime import BOLD, CYAN, GRAY, GREEN, PROJECT_ROOT, RED, RESET, YELLOW, cprint


def _manager():
    from scripts.services.browser_worker_runtime import manager as manager_mod

    return manager_mod


def _format_epoch_utc(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _cmdline_matches_worker_main(cmdline: list[str]) -> bool:
    normalized = " ".join(cmdline).replace("\\", "/").lower()
    return "-m app.worker.main" in normalized or "app/worker/main.py" in normalized


def collect_worker_process_evidence(pid: int) -> dict[str, object]:
    """Collect process identity evidence for the unified worker PID."""
    evidence: dict[str, object] = {
        "pid": pid,
        "alive": False,
        "create_time": None,
        "create_time_iso": None,
        "cmdline": [],
        "matches_worker_main": False,
        "error": None,
    }
    try:
        import psutil

        proc = psutil.Process(pid)
        cmdline = proc.cmdline()
        create_time = float(proc.create_time())
        evidence.update(
            {
                "alive": proc.is_running(),
                "create_time": create_time,
                "create_time_iso": _format_epoch_utc(create_time),
                "cmdline": cmdline,
                "matches_worker_main": _cmdline_matches_worker_main(cmdline),
            }
        )
    except Exception as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"

    worker_snapshot = get_worker_runtime_fingerprint_snapshot()
    evidence["source_fingerprint"] = worker_snapshot["source_fingerprint"]
    evidence["source_files"] = [item["path"] for item in worker_snapshot["source_files"]]
    return evidence


def evaluate_worker_restart_evidence(before: dict[str, object] | None, after: dict[str, object] | None) -> dict[str, object]:
    """Evaluate whether after evidence proves a fresh worker process."""
    if not after or not after.get("alive"):
        return {"ok": False, "reason": "worker_not_running"}
    if not after.get("matches_worker_main"):
        return {"ok": False, "reason": "worker_cmdline_mismatch"}
    if not before or not before.get("alive"):
        return {"ok": True, "reason": "worker_running_no_previous_process"}

    before_pid = before.get("pid")
    after_pid = after.get("pid")
    before_create_time = before.get("create_time")
    after_create_time = after.get("create_time")
    if before_pid == after_pid and before_create_time == after_create_time:
        return {"ok": False, "reason": "stale_worker_process"}
    if (
        isinstance(before_create_time, (int, float))
        and isinstance(after_create_time, (int, float))
        and after_create_time <= before_create_time
    ):
        return {"ok": False, "reason": "worker_create_time_not_newer"}
    return {"ok": True, "reason": "worker_process_replaced"}


def _print_redis_status(manager):
    try:
        import redis as redis_lib

        r = redis_lib.Redis(host="localhost", port=6379, socket_connect_timeout=3, decode_responses=True)
        r.ping()
        info = r.info(section="server")
        uptime = info.get("uptime_in_seconds", 0)
        mem_info = r.info(section="memory")
        used_mb = round(mem_info.get("used_memory", 0) / 1024 / 1024, 1)
        clients = r.info(section="clients").get("connected_clients", 0)
        r.close()
        print(f"  {GREEN}[+] Redis (uptime: {uptime}s, mem: {used_mb}MB, clients: {clients}){RESET}")
    except Exception:
        print(f"  {RED}[-] Redis: Not connected{RESET}")


def status(manager):
    mgr = _manager()
    print(f"\n{CYAN}{'=' * 40}")
    print(f"  Browser Workers Status")
    print(f"  (WorkerOrchestrator Architecture){RESET}")
    print(f"{CYAN}{'=' * 40}{RESET}\n")

    manager._print_redis_status()

    for w in manager.workers:
        pid_path = manager.pid_dir / w["pid_file"]
        pid = mgr.read_pid_file(pid_path)
        name = w["name"]
        if pid and mgr.is_process_alive(pid):
            print(f"  {GREEN}[+] {name} (PID: {pid}){RESET}")
        else:
            print(f"  {YELLOW}[-] {name}: Not running{RESET}")

    manager._print_frontend_status(public=False)
    manager._print_frontend_status(public=True)

    print(f"\n  {BOLD}Worker Processes:{RESET}")
    worker_names = {
        f"unified_worker{manager.pid_suffix}.pid": "Unified Worker (via Orchestrator, incl. video-dl)",
        f"claude_worker{manager.pid_suffix}.pid": "Claude Worker",
        "kakao_notification_listener.pid": "Kakao Notification Listener",
    }
    for pf, name in worker_names.items():
        pid_path = manager.pid_dir / pf
        pid = mgr.read_pid_file(pid_path)
        if pid and mgr.is_process_alive(pid):
            print(f"    {GREEN}[+] {name} (PID: {pid}){RESET}")
            if pf == f"unified_worker{manager.pid_suffix}.pid":
                evidence = collect_worker_process_evidence(pid)
                cmdline = " ".join(str(part) for part in evidence.get("cmdline", []))
                print(
                    f"        {GRAY}created={evidence.get('create_time_iso')} "
                    f"worker_main={evidence.get('matches_worker_main')} "
                    f"source={evidence.get('source_fingerprint')}{RESET}"
                )
                if cmdline:
                    print(f"        {GRAY}cmdline={cmdline}{RESET}")
        else:
            print(f"    {YELLOW}[-] {name}: Not running{RESET}")

    guard_state_path = PROJECT_ROOT / "logs" / "kakao_guard_state.json"
    if guard_state_path.exists():
        try:
            state = json.loads(guard_state_path.read_text(encoding="utf-8"))
            color = GREEN if state.get("state") == "released" else YELLOW
            print(
                f"    {color}[~] Kakao Input Guard: {state.get('state')} "
                f"(pid={state.get('pid')}, session={state.get('session_id')}){RESET}"
            )
        except Exception as exc:
            print(f"    {YELLOW}[?] Kakao Input Guard state unreadable: {exc}{RESET}")

    has_legacy = False
    for pf in manager.legacy_pid_files:
        pid = mgr.read_pid_file(manager.pid_dir / pf)
        if pid and mgr.is_process_alive(pid):
            if not has_legacy:
                print(f"\n  {YELLOW}Legacy Processes (should be cleaned up):{RESET}")
                has_legacy = True
            print(f"    {YELLOW}[!] {pf} (PID: {pid}){RESET}")

    if has_legacy:
        print(f"    {GRAY}Run 'python scripts/services/browser_workers.py restart' to clean up{RESET}")
    print()


def redis_status(manager):
    print(f"\n{CYAN}{'=' * 40}")
    print(f"  Redis Status")
    print(f"{'=' * 40}{RESET}\n")

    try:
        import redis as redis_lib

        r = redis_lib.Redis(host="localhost", port=6379, socket_connect_timeout=3, decode_responses=True)
        r.ping()
        print(f"  {GREEN}[+] Redis connection: OK (PONG){RESET}")

        info = r.info(section="server")
        print(f"      Uptime: {info.get('uptime_in_seconds', '?')}s")
        print(f"      Version: {info.get('redis_version', '?')}")

        mem_info = r.info(section="memory")
        used_mb = round(mem_info.get("used_memory", 0) / 1024 / 1024, 1)
        print(f"      Memory: {used_mb}MB")

        clients = r.info(section="clients").get("connected_clients", 0)
        client_list = r.client_list()
        pubsub_count = sum(1 for c in client_list if "S" in c.get("flags", "") or c.get("cmd") == "subscribe")
        print(f"      Clients: {clients} (pubsub: {pubsub_count})")
        r.close()
    except Exception as e:
        print(f"  {RED}[-] Redis connection: FAILED ({e}){RESET}")

    try:
        result = subprocess.run(
            ["podman", "inspect", "--format", "{{.State.Running}}", "monitor-redis"],
            **with_text_subprocess_defaults(
                capture_output=True,
                text=True,
                timeout=5,
            ),
        )
        if result.returncode == 0:
            running = result.stdout.strip().lower() == "true"
            color = GREEN if running else RED
            print(f"  {color}{'[+]' if running else '[-]'} Container monitor-redis: {'Running' if running else 'Stopped'}{RESET}")
        else:
            print(f"  {YELLOW}[?] Container monitor-redis: not found{RESET}")
    except Exception as e:
        print(f"  {YELLOW}[?] Podman check failed: {e}{RESET}")
    print()


def redis_restart(manager):
    print(f"\n{YELLOW}{'=' * 40}")
    print(f"  Restarting Redis")
    print(f"{'=' * 40}{RESET}\n")

    compose_path = PROJECT_ROOT / ".venv" / "Scripts" / "podman-compose.exe"
    if not compose_path.exists():
        compose_cmd = "podman-compose"
    else:
        compose_cmd = str(compose_path)

    socket_check = subprocess.run(["podman", "ps"], capture_output=True, timeout=5)
    if socket_check.returncode != 0:
        cprint("Podman socket unreachable — recycling Machine to re-establish SSH tunnel...", YELLOW)
        subprocess.run(["podman", "machine", "stop"], capture_output=True, timeout=15)
        time.sleep(3)
        start_result = subprocess.run(["podman", "machine", "start"], capture_output=True, timeout=60)
        if start_result.returncode != 0:
            cprint("Machine start failed — manual intervention required: podman machine stop && podman machine start", RED)
            return
        time.sleep(15)
        recheck = subprocess.run(["podman", "ps"], capture_output=True, timeout=5)
        if recheck.returncode != 0:
            cprint("Machine recycle failed — manual intervention required: podman machine stop && podman machine start", RED)
            return

    cprint("Starting Redis container via podman-compose...")
    try:
        result = subprocess.run(
            [compose_cmd, "up", "-d", "redis"],
            cwd=str(PROJECT_ROOT),
            **with_text_subprocess_defaults(
                capture_output=True,
                text=True,
                timeout=30,
            ),
        )
        if result.returncode != 0:
            cprint(f"podman-compose failed: {result.stderr.strip()}", RED)
            return
        cprint("Container started, waiting 3s...", YELLOW)
        time.sleep(3)

        try:
            import redis as redis_lib

            r = redis_lib.Redis(host="localhost", port=6379, socket_connect_timeout=3)
            r.ping()
            r.close()
            cprint("Redis is healthy (PONG)", GREEN)
        except Exception:
            cprint("Redis container started but connection not ready yet", YELLOW)
    except subprocess.TimeoutExpired:
        cprint("podman-compose timed out (30s)", RED)
    except Exception as e:
        cprint(f"Failed to restart Redis: {e}", RED)


def redis_cleanup(manager, dry_run: bool = False):
    print(f"\n{CYAN}{'=' * 40}")
    print(f"  Redis Zombie Cleanup{'  [DRY RUN]' if dry_run else ''}")
    print(f"{'=' * 40}{RESET}\n")

    try:
        from app.shared.redis.cleanup import kill_zombie_connections_sync

        result = kill_zombie_connections_sync(dry_run=dry_run)
        found = result.get("found", 0)
        killed = result.get("killed", 0)
        errors = result.get("errors", [])
        connections = result.get("connections", [])

        if found == 0:
            print(f"  {GREEN}[+] 좀비 연결 없음{RESET}")
        else:
            color = YELLOW if dry_run else RED
            print(f"  {color}[!] 좀비 연결 감지: {found}건{RESET}")
            for c in connections:
                print(f"      id={c['id']} addr={c['addr']} idle={c['idle']}s cmd={c['cmd']} flags={c['flags']}")
            if dry_run:
                print(f"\n  {YELLOW}[DRY RUN] kill 없이 목록만 출력됨{RESET}")
            else:
                print(f"\n  {GREEN}[+] kill 완료: {killed}/{found}건{RESET}")
        if errors:
            for err in errors:
                print(f"  {RED}[!] 오류: {err}{RESET}")
    except Exception as e:
        print(f"  {RED}[-] 좀비 정리 실패: {e}{RESET}")
    print()
