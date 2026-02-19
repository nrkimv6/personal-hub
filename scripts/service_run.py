"""Monitor Page 서비스 러너 (service-run.ps1 Python 교체).

NSSM 서비스로 등록되어 실행된다:
  nssm set MonitorPage-Dev Application python.exe
  nssm set MonitorPage-Dev AppParameters "scripts\\service_run.py --dev"

수동 실행:
  .venv\\Scripts\\python.exe scripts/service_run.py --dev
"""
import argparse
import atexit
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (app 패키지 import용)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from scripts.service_utils import (
    find_pids_on_port,
    get_session_id,
    is_port_listening,
    is_process_alive,
    kill_pid,
    read_pid_file,
    remove_pid_file,
    setup_service_logger,
    write_pid_file,
)

import psutil


class ServiceRunner:
    def __init__(self, dev: bool):
        self.dev = dev
        self.api_port = 8001 if dev else 8000
        self.frontend_port = 6101 if dev else 6100
        self.app_mode = "development" if dev else "production"
        self.pid_suffix = "_dev" if dev else ""

        self.log_dir = PROJECT_ROOT / "logs" / ("dev" if dev else "")
        self.pid_dir = PROJECT_ROOT / ".pids"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.pid_dir.mkdir(parents=True, exist_ok=True)

        self.log = setup_service_logger(
            "service_runner",
            self.log_dir / "service_runner.log",
        )

        self._frontend_proc: subprocess.Popen | None = None
        self._cleaned_up = False

    # ── 메인 실행 흐름 ──────────────────────────────────────────
    def run(self):
        self.log.info("=" * 50)
        self.log.info("Monitor Page Service Starting")
        self.log.info(f"Mode: {self.app_mode} | API: {self.api_port} | Frontend: {self.frontend_port}")
        self.log.info("=" * 50)

        self.log_environment()

        # 종료 핸들러 등록
        atexit.register(self.cleanup)
        signal.signal(signal.SIGBREAK, self._signal_handler)  # type: ignore[attr-defined]
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            self.cleanup_before_start()
            self._frontend_proc = self.start_frontend()
            self.log.info("Redis will be started via startup program (requires user session)")
            self.run_api()
        except KeyboardInterrupt:
            self.log.info("KeyboardInterrupt received")
        except Exception as e:
            self.log.error(f"Service failed: {e}", exc_info=True)
        finally:
            self.cleanup()
            sys.exit(1)

    # ── 환경 진단 ────────────────────────────────────────────────
    def log_environment(self):
        session_id = get_session_id()
        self.log.info(f"PID: {os.getpid()} | Session: {session_id} | Python: {sys.version.split()[0]}")
        self.log.info(f"CWD: {os.getcwd()}")
        if session_id == 0:
            self.log.warning("Session 0 detected — Telegram/Desktop notifications will be disabled by API")
        # DNS 테스트
        import socket
        try:
            socket.getaddrinfo("localhost", None)
            self.log.info("DNS: localhost resolution OK")
        except Exception as e:
            self.log.warning(f"DNS: localhost resolution FAILED: {e}")

    # ── 시작 전 정리 ────────────────────────────────────────────
    def cleanup_before_start(self):
        self.log.info("Cleaning up stale PIDs and ports...")
        self._cleanup_stale_pids()
        self._cleanup_orphan_vite()
        self._cleanup_ports()

    def _cleanup_stale_pids(self):
        # 자기 suffix에 해당하는 PID 파일만 처리 (prod: api.pid, dev: api_dev.pid)
        own_patterns = [f"api{self.pid_suffix}.pid", f"frontend{self.pid_suffix}.pid"]
        for pid_file in self.pid_dir.glob("*.pid"):
            if pid_file.name not in own_patterns:
                continue
            pid = read_pid_file(pid_file)
            if pid is None:
                remove_pid_file(pid_file)
                continue
            if is_process_alive(pid):
                self.log.info(f"  Killing orphan PID {pid} from {pid_file.name}")
                kill_pid(pid, logger=self.log)
            else:
                self.log.info(f"  Cleaned stale PID file: {pid_file.name} (PID {pid} dead)")
            remove_pid_file(pid_file)

    def _cleanup_orphan_vite(self):
        # 자기 포트의 vite만 정리, 다른 포트(dev/prod)의 vite는 건드리지 않음
        other_port = 6101 if self.frontend_port == 6100 else 6100
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if proc.info["name"] != "node.exe":
                    continue
                cmdline = " ".join(proc.info["cmdline"] or [])
                if "vite" not in cmdline:
                    continue
                if f"--port {self.frontend_port}" in cmdline:
                    continue  # 자기 포트의 정상 vite → 스킵
                if f"--port {other_port}" in cmdline:
                    continue  # 상대 서비스(dev/prod)의 vite → 스킵
                self.log.info(f"  Killing orphan Vite (PID: {proc.pid})")
                kill_pid(proc.pid, logger=self.log)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def _cleanup_ports(self):
        for port in [self.api_port, self.frontend_port]:
            pids = find_pids_on_port(port)
            if not pids:
                self.log.info(f"  Port {port}: available")
                continue
            for pid in pids:
                try:
                    name = psutil.Process(pid).name()
                except psutil.NoSuchProcess:
                    continue
                self.log.info(f"  Port {port}: killing {name} (PID: {pid})")
                kill_pid(pid, logger=self.log)
            # 포트 해제 대기
            for _ in range(6):
                if not find_pids_on_port(port):
                    break
                time.sleep(0.5)
            remaining = find_pids_on_port(port)
            if remaining:
                self.log.warning(f"  Port {port} still in use (PIDs: {remaining})")

    # ── Frontend 시작 ────────────────────────────────────────────
    def start_frontend(self) -> subprocess.Popen:
        self.log.info("Starting Frontend...")
        frontend_dir = PROJECT_ROOT / "frontend"
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        # node_modules 확인
        if not (frontend_dir / "node_modules").exists():
            self.log.info("Running npm install...")
            subprocess.run(["npm.cmd", "install"], cwd=str(frontend_dir), check=False)

        if self.dev:
            # Stale build 삭제
            build_dir = frontend_dir / "build"
            if build_dir.exists():
                shutil.rmtree(build_dir, ignore_errors=True)
                self.log.info("Cleaned up stale build directory")

            # .env.development.local
            env_file = frontend_dir / ".env.development.local"
            env_file.write_text(f"VITE_API_PORT={self.api_port}\n", encoding="utf-8")
            os.environ["VITE_API_PORT"] = str(self.api_port)

            stdout_log = open(self.log_dir / f"frontend_{timestamp}.log", "w", encoding="utf-8")
            stderr_log = open(self.log_dir / f"frontend_err_{timestamp}.log", "w", encoding="utf-8")

            proc = subprocess.Popen(
                ["npm.cmd", "run", "dev", "--", "--host", "--port", str(self.frontend_port)],
                cwd=str(frontend_dir),
                stdout=stdout_log,
                stderr=stderr_log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            # Production: build → preview
            self.log.info("Building frontend for production...")
            build_result = subprocess.run(
                ["npm.cmd", "run", "build"],
                cwd=str(frontend_dir),
                capture_output=True,
                text=True,
            )
            if build_result.returncode != 0:
                self.log.error(f"Frontend build failed: {build_result.stderr[-500:]}")
                raise RuntimeError("Frontend build failed")
            self.log.info("Frontend build completed")

            # .env.local 제거 (production에서 dev 설정 방지)
            env_local = frontend_dir / ".env.local"
            if env_local.exists():
                env_local.unlink()

            stdout_log = open(self.log_dir / f"frontend_{timestamp}.log", "w", encoding="utf-8")
            stderr_log = open(self.log_dir / f"frontend_err_{timestamp}.log", "w", encoding="utf-8")

            proc = subprocess.Popen(
                ["npm.cmd", "run", "preview", "--", "--host", "--port", str(self.frontend_port)],
                cwd=str(frontend_dir),
                stdout=stdout_log,
                stderr=stderr_log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

        pid_file = self.pid_dir / f"frontend{self.pid_suffix}.pid"
        write_pid_file(pid_file, proc.pid)
        self.log.info(f"Frontend started (PID: {proc.pid})")
        return proc

    # ── API 실행 (in-process) ────────────────────────────────────
    def run_api(self):
        self.log.info("Starting API Server in-process...")
        if self.dev:
            self.log.info("Development mode (hot reload disabled for stability)")

        # 환경변수
        os.environ["API_PORT"] = str(self.api_port)
        os.environ["WORKER_AUTO_START"] = "false"
        os.environ["APP_MODE"] = self.app_mode
        os.environ["PYTHONIOENCODING"] = "utf-8"

        # 단계별 import (hang 진단용)
        t = time.time()
        self.log.info("Importing app.config...")
        from app.config import settings  # noqa: F401
        self.log.info(f"  app.config imported ({time.time() - t:.1f}s)")

        t = time.time()
        self.log.info("Importing app.main...")
        from app.main import app  # noqa: F811
        self.log.info(f"  app.main imported ({time.time() - t:.1f}s)")

        t = time.time()
        self.log.info("Creating uvicorn server...")
        import uvicorn
        from app.core.server_state import set_server

        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=self.api_port,
            workers=1,
            log_level="info",
            loop="asyncio",
            limit_concurrency=1000,
            timeout_keep_alive=60,
            timeout_graceful_shutdown=30,
        )
        server = uvicorn.Server(config)
        set_server(server)
        self.log.info(f"  uvicorn configured ({time.time() - t:.1f}s)")

        # PID 저장
        api_pid_file = self.pid_dir / f"api{self.pid_suffix}.pid"
        write_pid_file(api_pid_file, os.getpid())
        self.log.info(f"API Server starting on port {self.api_port} (PID: {os.getpid()})...")

        # 블로킹 — uvicorn 이벤트 루프 실행
        server.run()

        self.log.info("API Server exited")

    # ── Cleanup ──────────────────────────────────────────────────
    def cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self.log.info("Service stopping, running cleanup...")

        # Frontend 종료
        if self._frontend_proc and self._frontend_proc.poll() is None:
            self.log.info(f"Stopping Frontend (PID: {self._frontend_proc.pid})...")
            kill_pid(self._frontend_proc.pid, logger=self.log)

        # PID 파일 정리
        for pattern in [f"api{self.pid_suffix}.pid", f"frontend{self.pid_suffix}.pid"]:
            pid_file = self.pid_dir / pattern
            remove_pid_file(pid_file)

        self.log.info("Service stopped")

    def _signal_handler(self, signum, frame):
        self.log.info(f"Signal {signum} received, shutting down...")
        self.cleanup()
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Monitor Page Service Runner")
    parser.add_argument("--dev", action="store_true", help="Development mode (port 8001/6101)")
    args = parser.parse_args()

    runner = ServiceRunner(dev=args.dev)
    runner.run()


if __name__ == "__main__":
    main()
