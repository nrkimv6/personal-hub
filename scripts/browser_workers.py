"""Browser Workers 관리 CLI (browser-workers.ps1 Python 교체).

Usage:
  python scripts/browser_workers.py start
  python scripts/browser_workers.py stop
  python scripts/browser_workers.py restart
  python scripts/browser_workers.py status
  python scripts/browser_workers.py restart-api
  python scripts/browser_workers.py restart-frontend
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from scripts.service_utils import (
    find_pids_on_port,
    is_port_listening,
    is_process_alive,
    kill_pid,
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


class BrowserWorkerManager:
    def __init__(self):
        self.pid_dir = PROJECT_ROOT / ".pids"
        self.log_dir = PROJECT_ROOT / "logs" / "dev"
        self.scripts_dir = PROJECT_ROOT / "scripts"
        self.frontend_dir = PROJECT_ROOT / "frontend"
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.pid_suffix = "_dev"
        self.api_port = 8001
        self.frontend_port = 6101

        # venv python
        self.python_exe = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        if not self.python_exe.exists():
            self.python_exe = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"

        # Watchdog/Listener 정의: (이름, PID파일명, 시작 명령)
        self.workers = [
            {
                "name": "Worker Watchdog (all workers via WorkerOrchestrator)",
                "pid_file": f"worker_watchdog{self.pid_suffix}.pid",
                "cmd": ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File",
                        str(self.scripts_dir / "unified-worker-watchdog.ps1")],
                "env": {"APP_MODE": "development"},
            },
            {
                "name": "Claude Worker Watchdog",
                "pid_file": f"claude_watchdog{self.pid_suffix}.pid",
                "cmd": ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File",
                        str(self.scripts_dir / "claude-watchdog.ps1")],
                "env": {"APP_MODE": "development"},
            },
            {
                "name": "Video Download Watchdog",
                "pid_file": f"video_download_watchdog{self.pid_suffix}.pid",
                "cmd": ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File",
                        str(self.scripts_dir / "video-download-watchdog.ps1")],
                "env": {"APP_MODE": "development"},
            },
            {
                "name": "Redis Command Listener",
                "pid_file": f"command_listener{self.pid_suffix}.pid",
                "cmd": [str(self.python_exe),
                        str(self.scripts_dir / "worker-command-listener.py")],
                "env": {},
            },
            {
                "name": "Auto-Next Command Listener",
                "pid_file": f"auto_next_command_listener{self.pid_suffix}.pid",
                "cmd": [str(self.python_exe),
                        str(self.scripts_dir / "auto-next-command-listener.py")],
                "env": {},
            },
        ]

        # 실제 워커 프로세스 PID 파일 (stop 시 정리)
        self.worker_pid_files = [
            f"unified_worker{self.pid_suffix}.pid",
            f"claude_worker{self.pid_suffix}.pid",
            f"video_download_worker{self.pid_suffix}.pid",
        ]

        # Legacy PID 파일
        self.legacy_pid_files = [
            f"watchdog{self.pid_suffix}.pid",
            f"crawl_watchdog{self.pid_suffix}.pid",
            f"worker{self.pid_suffix}.pid",
            f"crawl_worker{self.pid_suffix}.pid",
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
            proc = subprocess.Popen(
                w["cmd"],
                cwd=str(PROJECT_ROOT),
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            write_pid_file(pid_path, proc.pid)
            cprint(f"{w['name']} started (PID: {proc.pid})", GREEN)
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
                kill_pid(pid)
                stopped += 1
            remove_pid_file(pid_path)

        self._cleanup_legacy()

        if stopped > 0:
            cprint(f"{stopped} process(es) stopped", GREEN)
        else:
            cprint("No watchdogs were running", YELLOW)

    # ── restart ──────────────────────────────────────────────────
    def restart(self):
        self.stop()
        time.sleep(2)
        self.start()

    # ── restart-api ──────────────────────────────────────────────
    def restart_api(self):
        print(f"\n{YELLOW}{'=' * 40}")
        print(f"  Restarting API Server")
        print(f"  (Hot reload disabled - manual restart){RESET}")
        print(f"{YELLOW}{'=' * 40}{RESET}\n")

        url = f"http://localhost:{self.api_port}/api/v1/system/self-restart?delay=2"

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
    def restart_frontend(self):
        print(f"\n{YELLOW}{'=' * 40}")
        print(f"  Restarting DEV Frontend")
        print(f"  (Vite dev server on port {self.frontend_port}){RESET}")
        print(f"{YELLOW}{'=' * 40}{RESET}\n")

        pid_file = self.pid_dir / f"frontend{self.pid_suffix}.pid"
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        # 1. PID 파일에서 기존 프로세스 Kill
        pid = read_pid_file(pid_file)
        if pid and is_process_alive(pid):
            cprint(f"Stopping frontend process (PID: {pid})...")
            kill_pid(pid)
        remove_pid_file(pid_file)

        # 2. 포트 점유 프로세스 Kill
        for p in find_pids_on_port(self.frontend_port):
            cprint(f"Killing process on port {self.frontend_port} (PID: {p})...")
            kill_pid(p)

        # 3. Vite 고아 프로세스 정리
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if proc.info["name"] != "node.exe":
                    continue
                cmdline = " ".join(proc.info["cmdline"] or [])
                if "vite" in cmdline and f"--port {self.frontend_port}" in cmdline:
                    cprint(f"Killing orphan Vite process (PID: {proc.pid})...")
                    kill_pid(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        time.sleep(2)

        # 4. .env.development.local
        env_file = self.frontend_dir / ".env.development.local"
        env_file.write_text(f"VITE_API_PORT={self.api_port}\n", encoding="utf-8")

        # 5. Stale build 삭제
        build_dir = self.frontend_dir / "build"
        if build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)
            cprint("Cleaned up stale build directory")

        # 6. npm run dev
        cprint(f"Starting frontend (npm run dev --port {self.frontend_port})...")
        stdout_log = open(self.log_dir / f"frontend_{timestamp}.log", "w", encoding="utf-8")
        stderr_log = open(self.log_dir / f"frontend_err_{timestamp}.log", "w", encoding="utf-8")

        proc = subprocess.Popen(
            ["npm.cmd", "run", "dev", "--", "--host", "--port", str(self.frontend_port)],
            cwd=str(self.frontend_dir),
            stdout=stdout_log,
            stderr=stderr_log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        write_pid_file(pid_file, proc.pid)
        cprint(f"Frontend started (PID: {proc.pid})", GREEN)

        # 7. 헬스체크
        cprint("Waiting 5s for frontend to initialize...")
        time.sleep(5)
        try:
            with urllib.request.urlopen(
                f"http://localhost:{self.frontend_port}", timeout=5
            ) as resp:
                if resp.status == 200:
                    cprint(f"Frontend is healthy (http://localhost:{self.frontend_port})", GREEN)
        except Exception:
            cprint("Frontend not responding yet (may still be starting)", YELLOW)

    # ── status ───────────────────────────────────────────────────
    def status(self):
        print(f"\n{CYAN}{'=' * 40}")
        print(f"  Browser Workers Status")
        print(f"  (WorkerOrchestrator Architecture){RESET}")
        print(f"{CYAN}{'=' * 40}{RESET}\n")

        # Watchdog/Listener 상태
        for w in self.workers:
            pid_path = self.pid_dir / w["pid_file"]
            pid = read_pid_file(pid_path)
            name = w["name"]
            if pid and is_process_alive(pid):
                print(f"  {GREEN}[+] {name} (PID: {pid}){RESET}")
            else:
                print(f"  {YELLOW}[-] {name}: Not running{RESET}")

        # Frontend
        frontend_pid_file = self.pid_dir / f"frontend{self.pid_suffix}.pid"
        pid = read_pid_file(frontend_pid_file)
        port_up = is_port_listening(self.frontend_port)
        if pid and is_process_alive(pid) and port_up:
            print(f"  {GREEN}[+] Frontend DEV :{self.frontend_port} (PID: {pid}){RESET}")
        elif port_up:
            print(f"  {YELLOW}[~] Frontend DEV :{self.frontend_port} (port listening, PID file stale){RESET}")
        else:
            print(f"  {YELLOW}[-] Frontend DEV :{self.frontend_port}: Not running{RESET}")

        # 실제 워커 프로세스
        print(f"\n  {BOLD}Worker Processes:{RESET}")
        worker_names = {
            f"unified_worker{self.pid_suffix}.pid": "Unified Worker (via Orchestrator)",
            f"claude_worker{self.pid_suffix}.pid": "Claude Worker",
            f"video_download_worker{self.pid_suffix}.pid": "Video Download Worker",
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
    parser = argparse.ArgumentParser(description="Browser Workers Management")
    parser.add_argument(
        "action",
        choices=["start", "stop", "restart", "status", "restart-api", "restart-frontend"],
        help="Action to perform",
    )
    args = parser.parse_args()

    mgr = BrowserWorkerManager()
    action_map = {
        "start": mgr.start,
        "stop": mgr.stop,
        "restart": mgr.restart,
        "status": mgr.status,
        "restart-api": mgr.restart_api,
        "restart-frontend": mgr.restart_frontend,
    }
    action_map[args.action]()


if __name__ == "__main__":
    main()
