"""Browser Workers 관리 CLI (browser-workers.ps1 Python 교체).

Usage:
  python scripts/browser_workers.py start
  python scripts/browser_workers.py stop
  python scripts/browser_workers.py restart
  python scripts/browser_workers.py status
  python scripts/browser_workers.py restart-api
  python scripts/browser_workers.py restart-frontend
  python scripts/browser_workers.py restart-frontend --public
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.shared.process.tracked_popen import tracked_popen_sync
from scripts.service_utils import (
    find_pids_on_port,
    is_port_listening,
    is_process_alive,
    kill_pid,
    pick_listener_pid,
    read_pid_file,
    remove_pid_file,
    write_pid_file,
)

import psutil

# ── ANSI 컬러 ────────────────────────────────────────────────────
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"


def cprint(msg: str, color: str = RESET):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{GRAY}[{ts}]{RESET} {color}{msg}{RESET}")


def _kill_by_cmdline(pattern: str) -> int:
    """커맨드라인에 pattern이 포함된 프로세스를 찾아 종료한다. 종료된 수 반환.

    PID 파일 분실 시 잔류 프로세스 정리 용도 (2차 안전망).
    자기 자신과 조상 프로세스(부모/조부모 등)는 제외한다.
    """
    self_pid = os.getpid()
    # 자기 자신과 모든 조상 PID 수집 (browser_workers.py 실행 컨텍스트 보호)
    excluded_pids = {self_pid}
    try:
        for parent in psutil.Process(self_pid).parents():
            excluded_pids.add(parent.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    killed = 0
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.pid in excluded_pids:
                continue
            cmdline = proc.info.get("cmdline") or []
            if any(pattern in arg for arg in cmdline):
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed


class BrowserWorkerManager:
    def __init__(self):
        self.pid_dir = PROJECT_ROOT / ".pids"
        self.log_dir = PROJECT_ROOT / "logs" / "admin"
        self.scripts_dir = PROJECT_ROOT / "scripts"
        self.frontend_dir = PROJECT_ROOT / "frontend"
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.pid_suffix = "_admin"
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
                        str(self.scripts_dir / "unified-worker-watchdog.ps1")],
                "env": {"APP_MODE": "admin"},
                "role": "watchdog",
            },
            {
                "name": "Claude Worker Watchdog",
                "pid_file": f"claude_watchdog{self.pid_suffix}.pid",
                "cmd": [_ps_alias("monitorpage-wdog-claude.exe"), "-ExecutionPolicy", "Bypass", "-File",
                        str(self.scripts_dir / "claude-watchdog.ps1")],
                "env": {"APP_MODE": "admin"},
                "role": "claude_watchdog",
            },
            {
                "name": "Infra Command Listener",
                "pid_file": f"infra_command_listener{self.pid_suffix}.pid",
                "cmd": [str(self.python_exe),
                        str(self.scripts_dir / "infra-command-listener.py")],
                "env": {},
                "role": "infra_listener",
            },
            {
                "name": "Command Listener Watchdog",
                "pid_file": f"command_listener_watchdog{self.pid_suffix}.pid",
                "cmd": [_ps_alias("monitorpage-wdog-cmd.exe"), "-ExecutionPolicy", "Bypass", "-File",
                        str(self.scripts_dir / "command-listener-watchdog.ps1")],
                "env": {"APP_MODE": "admin"},
                "role": "listener",
            },
            {
                "name": "Dev Runner Command Listener",
                "pid_file": f"dev_runner_command_listener{self.pid_suffix}.pid",
                "cmd": [str(self.python_exe),
                        str(self.scripts_dir / "dev-runner-command-listener.py")],
                "env": {},
                "role": "dev_listener",
            },
            {
                "name": "Chat Executor Watchdog",
                "pid_file": f"chat_executor_watchdog{self.pid_suffix}.pid",
                "cmd": [_ps_alias("monitorpage-wdog-chat.exe"), "-ExecutionPolicy", "Bypass", "-File",
                        str(self.scripts_dir / "llm-chat-executor-watchdog.ps1")],
                "env": {"APP_MODE": "admin"},
                "role": "watchdog",
            },
        ]

        # 실제 워커 프로세스 PID 파일 (stop 시 정리)
        self.worker_pid_files = [
            f"unified_worker{self.pid_suffix}.pid",
            f"claude_worker{self.pid_suffix}.pid",
            f"command_listener{self.pid_suffix}.pid",
            f"chat_executor_admin.pid",
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

    # ── start ────────────────────────────────────────────────────
    def start(self):
        print(f"\n{CYAN}{'=' * 40}")
        print(f"  Starting Browser Workers")
        print(f"  (WorkerOrchestrator Architecture){RESET}")
        print(f"{CYAN}{'=' * 40}{RESET}\n")

        # Zombie 포트 체크
        if is_port_listening(self.api_port):
            pids = find_pids_on_port(self.api_port)
            if pids:
                cprint(f"Port {self.api_port} in use (PIDs: {pids})", GRAY)

        self._cleanup_legacy()
        started = 0

        for w in self.workers:
            pid_path = self.pid_dir / w["pid_file"]
            pid = read_pid_file(pid_path)
            if pid and is_process_alive(pid):
                cprint(f"{w['name']}: already running (PID: {pid})", YELLOW)
                continue

            # python.exe 필요한 워커인데 venv 없으면 스킵
            if str(self.python_exe) in " ".join(w["cmd"]) and not self.python_exe.exists():
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

            proc = tracked_popen_sync(
                w["cmd"],
                role=w.get("role", "watchdog"),
                cwd=str(PROJECT_ROOT),
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
                stderr=stderr_file,
            )
            write_pid_file(pid_path, proc.pid)
            cprint(f"{w['name']} started (PID: {proc.pid})", GREEN)

            if w["name"] == "Dev Runner Command Listener":
                time.sleep(0.5)
                if not is_process_alive(proc.pid):
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

    # ── stop ─────────────────────────────────────────────────────
    def stop(self):
        print(f"\n{RED}{'=' * 40}")
        print(f"  Stopping Browser Workers")
        print(f"{'=' * 40}{RESET}\n")

        stopped = 0

        # Watchdog/Listener 종료
        for w in self.workers:
            pid_path = self.pid_dir / w["pid_file"]
            pid = read_pid_file(pid_path)
            if pid and is_process_alive(pid):
                cprint(f"Stopping {w['name']} (PID: {pid})...")
                try:
                    from app.shared.process.registry import ProcessRegistry
                    asyncio.run(ProcessRegistry().unregister(pid))
                except Exception:
                    pass
                kill_pid(pid)
                cprint(f"{w['name']} stopped", GREEN)
                stopped += 1
            remove_pid_file(pid_path)

        # 실제 워커 프로세스 종료
        for pf in self.worker_pid_files:
            pid_path = self.pid_dir / pf
            pid = read_pid_file(pid_path)
            if pid and is_process_alive(pid):
                cprint(f"Stopping worker process (PID: {pid})...")
                try:
                    from app.shared.process.registry import ProcessRegistry
                    asyncio.run(ProcessRegistry().unregister(pid))
                except Exception:
                    pass
                kill_pid(pid)
                stopped += 1
            remove_pid_file(pid_path)

        self._cleanup_legacy()

        # 2차 안전망: PID 파일 분실 시 잔류 프로세스 커맨드라인 기반 정리
        leaked = _kill_by_cmdline("dev-runner-command-listener")
        if leaked:
            cprint(f"잔류 프로세스 {leaked}개 정리됨 (PID 파일 누락)", YELLOW)

        if stopped > 0 or leaked > 0:
            cprint(f"{stopped + leaked} process(es) stopped", GREEN)
        else:
            cprint("No watchdogs were running", YELLOW)

    # ── restart ──────────────────────────────────────────────────
    def restart(self):
        self.stop()
        time.sleep(2)
        self.start()

    # ── WMI 헬스체크 ─────────────────────────────────────────────
    def _check_wmi_health(self) -> bool:
        """WMI 서비스 정상 여부 확인. platform.machine() 호출이 5초 내 완료되면 True."""
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

    def _fix_wmi(self) -> bool:
        """WMI 서비스(winmgmt) 재시작. 성공 시 True."""
        try:
            result = subprocess.run(
                ["powershell", "-Command", "Restart-Service winmgmt -Force"],
                timeout=15,
                capture_output=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    # ── restart-api ──────────────────────────────────────────────
    def restart_api(self):
        print(f"\n{YELLOW}{'=' * 40}")
        print(f"  Restarting API Server")
        print(f"  (Hot reload disabled - manual restart){RESET}")
        print(f"{YELLOW}{'=' * 40}{RESET}\n")

        # WMI 사전 체크
        cprint("Checking WMI health...", YELLOW)
        if not self._check_wmi_health():
            cprint("WMI is unresponsive. Attempting to restart winmgmt service...", YELLOW)
            if self._fix_wmi():
                cprint("winmgmt restarted. Waiting 5s...", YELLOW)
                time.sleep(5)
                if self._check_wmi_health():
                    cprint("WMI recovered successfully.", GREEN)
                else:
                    cprint("WMI still unresponsive after restart. Proceeding anyway.", YELLOW)
            else:
                cprint("Failed to restart winmgmt (may need admin rights). Proceeding anyway.", YELLOW)
        else:
            cprint("WMI OK", GREEN)

        url = f"http://localhost:{self.api_port}/api/v1/system/self-restart?delay=2&reason=browser_workers_py"

        # 1순위: Self-Restart API
        try:
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    cprint("Self-restart API called (graceful shutdown)", GREEN)
        except Exception as e:
            cprint(f"Self-restart API unavailable: {e}", YELLOW)

            # 2순위: force kill → NSSM 자동 재시작
            pids = find_pids_on_port(self.api_port)
            if pids:
                for pid in pids:
                    cprint(f"Killing API process (PID: {pid})...")
                    kill_pid(pid)
                cprint("API process stopped. NSSM will auto-restart.", YELLOW)
            else:
                cprint(f"No process found on port {self.api_port}", YELLOW)

        # 헬스체크
        cprint("Waiting for API to restart...")
        time.sleep(5)
        try:
            with urllib.request.urlopen(
                f"http://localhost:{self.api_port}/api/v1/system/status", timeout=5
            ) as resp:
                if resp.status == 200:
                    cprint("API server is healthy", GREEN)
        except Exception:
            cprint("API not responding yet (may still be starting)", YELLOW)

    # ── restart-frontend ─────────────────────────────────────────
    def _frontend_mode(self, public: bool) -> tuple[str, int, int, Path, Path]:
        """frontend 실행 모드별 런타임 정보를 반환한다."""
        if public:
            mode_label = "PUBLIC PREVIEW"
            api_port = 8000
            frontend_port = 6100
            pid_file = self.pid_dir / "frontend.pid"
            log_dir = PROJECT_ROOT / "logs"
        else:
            mode_label = "ADMIN DEV"
            api_port = self.api_port
            frontend_port = self.frontend_port
            pid_file = self.pid_dir / f"frontend{self.pid_suffix}.pid"
            log_dir = PROJECT_ROOT / "logs" / "admin"
        log_dir.mkdir(parents=True, exist_ok=True)
        return mode_label, api_port, frontend_port, pid_file, log_dir

    def _acquire_frontend_restart_lock(self, wait_seconds: int = 10) -> int | None:
        """frontend 재시작 락을 획득한다. wait_seconds 내 실패 시 None."""
        deadline = time.time() + max(wait_seconds, 1)
        while time.time() <= deadline:
            try:
                fd = os.open(str(self.frontend_restart_lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
                return fd
            except FileExistsError:
                stale_pid = read_pid_file(self.frontend_restart_lock)
                if stale_pid and not is_process_alive(stale_pid):
                    remove_pid_file(self.frontend_restart_lock)
                    continue
                time.sleep(0.5)
            except Exception:
                return None
        return None

    def _release_frontend_restart_lock(self, lock_fd: int | None) -> None:
        """frontend 재시작 락을 해제한다."""
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except Exception:
                pass
        remove_pid_file(self.frontend_restart_lock)

    def _cleanup_frontend_runtime(self, frontend_port: int, pid_file: Path) -> None:
        """기존 PID/포트 점유/고아 node 프로세스를 정리한다."""
        pid = read_pid_file(pid_file)
        if pid and is_process_alive(pid):
            cprint(f"Stopping frontend process (PID: {pid})...")
            kill_pid(pid)
        remove_pid_file(pid_file)

        for pid_on_port in find_pids_on_port(frontend_port):
            cprint(f"Killing process on port {frontend_port} (PID: {pid_on_port})...")
            kill_pid(pid_on_port)

        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if proc.info["name"] != "node.exe":
                    continue
                cmdline = " ".join(proc.info.get("cmdline") or [])
                has_target_port = f"--port {frontend_port}" in cmdline
                has_frontend_server = "vite" in cmdline or "preview" in cmdline
                if has_target_port and has_frontend_server:
                    cprint(f"Killing orphan frontend process (PID: {proc.pid})...")
                    kill_pid(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def _prepare_frontend_env(self, api_port: int, public: bool) -> None:
        """모드별 환경 파일/아티팩트를 준비한다."""
        if public:
            env_local = self.frontend_dir / ".env.local"
            if env_local.exists():
                env_local.unlink()
            return

        env_file = self.frontend_dir / ".env.development.local"
        env_file.write_text(f"VITE_API_PORT={api_port}\n", encoding="utf-8")
        build_dir = self.frontend_dir / "build"
        if build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)
            cprint("Cleaned up stale build directory")

    def _run_frontend_build_if_needed(self, public: bool) -> bool:
        """public 모드에서 build 후 preview 가능 여부를 반환한다."""
        if not public:
            return True

        cprint("Building frontend for PUBLIC PREVIEW...", YELLOW)
        build_result = subprocess.run(
            ["npm.cmd", "run", "build"],
            cwd=str(self.frontend_dir),
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

        if not (self.frontend_dir / "build").exists():
            cprint("No previous build artifact found — cannot run PUBLIC PREVIEW", RED)
            return False

        cprint("Using previous build artifact for fallback preview", YELLOW)
        return True

    def _read_log_tail(self, log_path: Path, max_chars: int = 4000) -> str:
        if not log_path.exists():
            return ""
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""
        return content[-max_chars:]

    def _has_port_collision_error(self, stderr_log_path: Path, frontend_port: int) -> bool:
        tail = self._read_log_tail(stderr_log_path)
        return f"Port {frontend_port} is already in use" in tail

    def restart_frontend(self, public: bool = False) -> bool:
        mode_label, api_port, frontend_port, pid_file, log_dir = self._frontend_mode(public)
        print(f"\n{YELLOW}{'=' * 40}")
        print(f"  Restarting {mode_label} Frontend")
        print(f"  (port {frontend_port}){RESET}")
        print(f"{YELLOW}{'=' * 40}{RESET}\n")

        lock_fd = self._acquire_frontend_restart_lock(wait_seconds=10)
        if lock_fd is None:
            cprint("Frontend restart lock is busy; another restart is in progress", RED)
            return False

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        stdout_log_path = log_dir / f"frontend_{timestamp}.log"
        stderr_log_path = log_dir / f"frontend_err_{timestamp}.log"
        old_listener_pid = pick_listener_pid(frontend_port)
        if old_listener_pid:
            cprint(f"Pre-restart listener PID on :{frontend_port} = {old_listener_pid}", YELLOW)

        try:
            self._cleanup_frontend_runtime(frontend_port, pid_file)
            time.sleep(2)
            self._prepare_frontend_env(api_port=api_port, public=public)

            if not self._run_frontend_build_if_needed(public=public):
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
                proc = tracked_popen_sync(
                    start_cmd,
                    role="frontend",
                    cwd=str(self.frontend_dir),
                    stdout=stdout_log,
                    stderr=stderr_log,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            cprint(f"Frontend launcher started (PID: {proc.pid})", GREEN)

            cprint("Waiting 5s for frontend to initialize...")
            time.sleep(5)

            new_listener_pid = pick_listener_pid(frontend_port)
            if new_listener_pid is not None:
                write_pid_file(pid_file, new_listener_pid)
            elif is_process_alive(proc.pid):
                write_pid_file(pid_file, proc.pid)
            else:
                remove_pid_file(pid_file)

            if self._has_port_collision_error(stderr_log_path, frontend_port):
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
            self._release_frontend_restart_lock(lock_fd)

    def _print_frontend_status(self, public: bool = False):
        mode_label, _api_port, frontend_port, frontend_pid_file, _log_dir = self._frontend_mode(public)
        pid = read_pid_file(frontend_pid_file)
        port_up = is_port_listening(frontend_port)
        if pid and is_process_alive(pid) and port_up:
            print(f"  {GREEN}[+] Frontend {mode_label} :{frontend_port} (PID: {pid}){RESET}")
            return

        if port_up:
            listener_pid = pick_listener_pid(frontend_port)
            if listener_pid is not None:
                write_pid_file(frontend_pid_file, listener_pid)
                print(
                    f"  {YELLOW}[~] Frontend {mode_label} :{frontend_port} "
                    f"(PID file stale -> auto-healed to PID {listener_pid}){RESET}"
                )
            else:
                print(f"  {YELLOW}[~] Frontend {mode_label} :{frontend_port} (port listening, PID file stale){RESET}")
            return

        print(f"  {YELLOW}[-] Frontend {mode_label} :{frontend_port}: Not running{RESET}")

    # ── status ───────────────────────────────────────────────────
    def status(self):
        print(f"\n{CYAN}{'=' * 40}")
        print(f"  Browser Workers Status")
        print(f"  (WorkerOrchestrator Architecture){RESET}")
        print(f"{CYAN}{'=' * 40}{RESET}\n")

        # Redis 상태
        self._print_redis_status()

        # Watchdog/Listener 상태
        for w in self.workers:
            pid_path = self.pid_dir / w["pid_file"]
            pid = read_pid_file(pid_path)
            name = w["name"]
            if pid and is_process_alive(pid):
                print(f"  {GREEN}[+] {name} (PID: {pid}){RESET}")
            else:
                print(f"  {YELLOW}[-] {name}: Not running{RESET}")

        # Frontend (admin/public)
        self._print_frontend_status(public=False)
        self._print_frontend_status(public=True)

        # 실제 워커 프로세스
        print(f"\n  {BOLD}Worker Processes:{RESET}")
        worker_names = {
            f"unified_worker{self.pid_suffix}.pid": "Unified Worker (via Orchestrator, incl. video-dl)",
            f"claude_worker{self.pid_suffix}.pid": "Claude Worker",
        }
        for pf, name in worker_names.items():
            pid_path = self.pid_dir / pf
            pid = read_pid_file(pid_path)
            if pid and is_process_alive(pid):
                print(f"    {GREEN}[+] {name} (PID: {pid}){RESET}")
            else:
                print(f"    {YELLOW}[-] {name}: Not running{RESET}")

        # Legacy
        has_legacy = False
        for pf in self.legacy_pid_files:
            pid = read_pid_file(self.pid_dir / pf)
            if pid and is_process_alive(pid):
                if not has_legacy:
                    print(f"\n  {YELLOW}Legacy Processes (should be cleaned up):{RESET}")
                    has_legacy = True
                print(f"    {YELLOW}[!] {pf} (PID: {pid}){RESET}")

        if has_legacy:
            print(f"    {GRAY}Run 'python scripts/browser_workers.py restart' to clean up{RESET}")
        print()

    # ── redis helpers ────────────────────────────────────────────
    def _print_redis_status(self):
        """Redis 상태 한 줄 출력"""
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

    def redis_status(self):
        """Redis 상태 상세 조회"""
        print(f"\n{CYAN}{'=' * 40}")
        print(f"  Redis Status")
        print(f"{'=' * 40}{RESET}\n")

        # 1. Redis 연결
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
            # pubsub 연결 수 확인
            client_list = r.client_list()
            pubsub_count = sum(1 for c in client_list if "S" in c.get("flags", "") or c.get("cmd") == "subscribe")
            print(f"      Clients: {clients} (pubsub: {pubsub_count})")
            r.close()
        except Exception as e:
            print(f"  {RED}[-] Redis connection: FAILED ({e}){RESET}")

        # 2. Podman 컨테이너
        try:
            result = subprocess.run(
                ["podman", "inspect", "--format", "{{.State.Running}}", "monitor-redis"],
                capture_output=True, text=True, timeout=5,
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

    def redis_restart(self):
        """Redis 컨테이너 재시작"""
        print(f"\n{YELLOW}{'=' * 40}")
        print(f"  Restarting Redis")
        print(f"{'=' * 40}{RESET}\n")

        compose_path = PROJECT_ROOT / ".venv" / "Scripts" / "podman-compose.exe"
        if not compose_path.exists():
            compose_cmd = "podman-compose"
        else:
            compose_cmd = str(compose_path)

        # Podman 소켓 검증 — 소켓 끊김 시 Machine 재수립
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
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                cprint(f"podman-compose failed: {result.stderr.strip()}", RED)
                return
            cprint("Container started, waiting 3s...", YELLOW)
            time.sleep(3)

            # Ping 확인
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

    def redis_cleanup(self, dry_run: bool = False):
        """Redis 좀비 연결 감지 및 정리"""
        print(f"\n{CYAN}{'=' * 40}")
        print(f"  Redis Zombie Cleanup{'  [DRY RUN]' if dry_run else ''}")
        print(f"{'=' * 40}{RESET}\n")

        try:
            import sys
            sys.path.insert(0, str(PROJECT_ROOT))
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

    # ── restart-listener ─────────────────────────────────────────
    def restart_listener(self):
        """command_listener watchdog+worker를 kill 후 재시작한다."""
        print(f"\n{CYAN}{'=' * 40}")
        print(f"  Restarting Command Listener")
        print(f"{'=' * 40}{RESET}\n")

        # watchdog + worker PID kill
        listener_pids = [
            self.pid_dir / f"command_listener_watchdog{self.pid_suffix}.pid",
            self.pid_dir / f"command_listener{self.pid_suffix}.pid",
        ]
        for pid_path in listener_pids:
            pid = read_pid_file(pid_path)
            if pid and is_process_alive(pid):
                cprint(f"Stopping {pid_path.name} (PID: {pid})...", YELLOW)
                kill_pid(pid)
            remove_pid_file(pid_path)

        time.sleep(1)

        # Command Listener Watchdog만 재시작
        for w in self.workers:
            if w["role"] != "listener":
                continue
            pid_path = self.pid_dir / w["pid_file"]
            pid = read_pid_file(pid_path)
            if pid and is_process_alive(pid):
                cprint(f"{w['name']}: already running (PID: {pid})", YELLOW)
                continue
            cprint(f"Starting {w['name']}...")
            env = {**os.environ, **w["env"]}
            proc = tracked_popen_sync(
                w["cmd"],
                role=w.get("role", "watchdog"),
                cwd=str(PROJECT_ROOT),
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            write_pid_file(pid_path, proc.pid)
            cprint(f"{w['name']} started (PID: {proc.pid})", GREEN)

    # ── restart-infra ─────────────────────────────────────────────
    def restart_infra(self, target: str):
        """지정 infra 프로세스(target)의 watchdog+worker를 kill 후 watchdog만 재시작한다."""
        print(f"\n{CYAN}{'=' * 40}")
        print(f"  Restarting Infra: {target}")
        print(f"{'=' * 40}{RESET}\n")

        # config에서 infra workers 로드해 name 매칭
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
            pid = read_pid_file(pid_path)
            if pid and is_process_alive(pid):
                cprint(f"Stopping {pf} (PID: {pid})...", YELLOW)
                kill_pid(pid)
            remove_pid_file(pid_path)

        time.sleep(1)

        # watchdog 재시작 (self.workers에서 name 매칭)
        # command_listener 는 별도 restart_listener 사용; 여기선 나머지 infra 처리
        for w in self.workers:
            # pid_file 명으로 매칭 (watchdog_pid_file)
            wdog_pf = item.get("watchdog_pid_file")
            if not wdog_pf or w["pid_file"] != wdog_pf:
                continue
            pid_path = self.pid_dir / w["pid_file"]
            cprint(f"Starting {w['name']}...")
            env = {**os.environ, **w["env"]}
            proc = tracked_popen_sync(
                w["cmd"],
                role=w.get("role", "watchdog"),
                cwd=str(PROJECT_ROOT),
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            write_pid_file(pid_path, proc.pid)
            cprint(f"{w['name']} started (PID: {proc.pid})", GREEN)

    # ── legacy cleanup ───────────────────────────────────────────
    def _cleanup_legacy(self):
        for pf in self.legacy_pid_files:
            pid_path = self.pid_dir / pf
            pid = read_pid_file(pid_path)
            if pid and is_process_alive(pid):
                cprint(f"Stopping legacy process (PID: {pid}) from {pf}", YELLOW)
                kill_pid(pid)
            remove_pid_file(pid_path)


def main():
    if "--restart-frontend" in sys.argv[1:]:
        print(
            "error: '--restart-frontend' is not a valid option. "
            "Use positional action: python scripts/browser_workers.py restart-frontend [--public]",
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
        help="Use PUBLIC PREVIEW mode for restart-frontend (port 6100, build+preview)",
    )
    args = parser.parse_args()

    if args.public and args.action != "restart-frontend":
        parser.error("--public can only be used with restart-frontend")
    if args.action == "restart-infra" and not args.target:
        parser.error("restart-infra requires target argument")

    mgr = BrowserWorkerManager()
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
        raise SystemExit(0 if ok else 1)
    action_map[args.action]()


if __name__ == "__main__":
    main()
