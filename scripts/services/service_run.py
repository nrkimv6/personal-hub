"""Monitor Page 서비스 러너 (service-run.ps1 Python 교체).

NSSM 서비스로 등록되어 실행된다:
  nssm set MonitorPage-Admin Application python.exe
  nssm set MonitorPage-Admin AppParameters "scripts\\service_run.py --admin"

수동 실행:
  .venv\\Scripts\\python.exe scripts/service_run.py --admin
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

def _resolve_project_root() -> Path:
    current = Path(__file__).resolve()
    # 스텁 경유 실행(scripts/service_run.py)과 실제 파일 import 모두에서 repo root를 찾는다.
    for candidate in (current.parent, *current.parents):
        if all((candidate / marker).exists() for marker in ("app", "frontend", "scripts")):
            return candidate
    return current.parent.parent


def _resolve_bootstrap_app_mode(argv: list[str] | None = None) -> str:
    return "admin" if "--admin" in (argv or sys.argv[1:]) else "public"


def bootstrap_service_environment(argv: list[str] | None = None, env: dict[str, str] | None = None) -> str:
    target_env = os.environ if env is None else env
    app_mode = _resolve_bootstrap_app_mode(argv)
    target_env["APP_MODE"] = app_mode
    target_env["PYTHONIOENCODING"] = "utf-8"
    return app_mode


def get_runtime_fingerprint_snapshot(*args, **kwargs):
    from app.core.runtime_fingerprint import get_runtime_fingerprint_snapshot as _inner

    return _inner(*args, **kwargs)


def _normalize_app_mode(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"admin", "public"}:
            return normalized
    return "public"


def _log_mode_alignment(log, settings_mode: object) -> bool:
    env_mode = _normalize_app_mode(os.environ.get("APP_MODE"))
    runtime_mode = _normalize_app_mode(get_runtime_fingerprint_snapshot().get("app_mode"))
    normalized_settings_mode = _normalize_app_mode(settings_mode)
    aligned = env_mode == normalized_settings_mode == runtime_mode

    log.info(
        "Mode alignment: env=%s | settings=%s | runtime=%s",
        env_mode,
        normalized_settings_mode,
        runtime_mode,
    )
    if not aligned:
        log.warning(
            "Mode alignment drift detected: env=%s | settings=%s | runtime=%s",
            env_mode,
            normalized_settings_mode,
            runtime_mode,
        )
    return aligned


PROJECT_ROOT = _resolve_project_root()
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from scripts.services.service_utils import (
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
from scripts.services.frontend_mode import (
    build_frontend_env,
    ensure_frontend_runtime_tsconfigs,
    describe_frontend_runtime,
)

import psutil


class ServiceRunner:
    def __init__(self, dev: bool):
        self.dev = dev
        self.api_port = 8001 if dev else 8000
        self.frontend_port = 6101 if dev else 6100
        self.app_mode = "admin" if dev else "public"
        self.pid_suffix = "_admin" if dev else ""

        self.log_dir = PROJECT_ROOT / "logs" / ("admin" if dev else "")
        self.pid_dir = PROJECT_ROOT / ".pids"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.pid_dir.mkdir(parents=True, exist_ok=True)

        self.log = setup_service_logger(
            "service_runner",
            self.log_dir,
        )

        self._frontend_proc: subprocess.Popen | None = None
        self._cleaned_up = False

    def _frontend_runtime_env(self, public: bool) -> dict[str, str]:
        api_port = None if public else self.api_port
        return build_frontend_env(os.environ, public=public, api_port=api_port)

    # ── 메인 실행 흐름 ──────────────────────────────────────────
    def run(self):
        bootstrap_service_environment(["--admin"] if self.dev else [])

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
            self._exit_code = 1
        finally:
            self.cleanup()
            sys.exit(getattr(self, '_exit_code', 0))

    # ── 환경 진단 ────────────────────────────────────────────────
    def log_environment(self):
        session_id = get_session_id()
        self.log.info(f"PID: {os.getpid()} | Session: {session_id} | Python: {sys.version.split()[0]}")
        self.log.info(f"Script: {Path(__file__).resolve()}")
        self.log.info(f"PROJECT_ROOT: {PROJECT_ROOT}")
        self.log.info(f"sys.path[0]: {sys.path[0] if sys.path else ''}")
        self.log.info(f"CWD: {os.getcwd()}")
        fingerprint = get_runtime_fingerprint_snapshot()
        self.log.info(
            "Runtime fingerprint: "
            f"{fingerprint['runtime_fingerprint'][:12]}... | "
            f"source={fingerprint['source_fingerprint'][:12]}... | "
            f"files={len(fingerprint['source_files'])}"
        )
        if session_id == 0:
            self.log.info("Session 0 detected - Telegram notifications active (HTTP API works in Session 0); Desktop notifications will be relayed via Redis to Session 1")
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
    def start_frontend(self) -> subprocess.Popen | None:
        """정책 고정: admin은 DEV, public은 BUILD+PREVIEW로 시작한다.

        - admin(dev=True): `npm run dev -- --host --port 6101`
        - public(dev=False): `npm run build` 후 `npm run preview -- --host --port 6100`
          (build 실패 시 기존 `build/`가 있으면 fallback preview)
        """
        self.log.info("Starting Frontend...")
        frontend_dir = PROJECT_ROOT / "frontend"
        frontend_env = self._frontend_runtime_env(public=not self.dev)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.log.info(f"Frontend runtime contract: {describe_frontend_runtime(public=not self.dev)}")
        ensure_frontend_runtime_tsconfigs(frontend_dir)

        # frontend 의존성 확인 (node_modules 디렉토리만 믿지 말고 vite 실행 파일도 확인)
        node_modules_dir = frontend_dir / "node_modules"
        vite_bin = node_modules_dir / ".bin" / "vite.cmd"
        deps_reason = None
        if not node_modules_dir.exists():
            deps_reason = "node_modules missing"
        elif not vite_bin.exists():
            deps_reason = "vite binary missing"

        if deps_reason:
            self.log.warning(f"Frontend dependency check: {deps_reason}; running npm install...")
            subprocess.run(
                ["npm.cmd", "install"],
                cwd=str(frontend_dir),
                check=False,
                encoding="utf-8",
                errors="replace",
                env=frontend_env,
            )
            if not vite_bin.exists():
                self.log.error("Vite binary is still missing after npm install; frontend start may fail")

        if self.dev:
            # Stale build ??
            build_dir = frontend_dir / "build"
            if build_dir.exists():
                shutil.rmtree(build_dir, ignore_errors=True)
                self.log.info("Cleaned up stale build directory")

            # .env.development.local
            env_file = frontend_dir / ".env.development.local"
            env_file.write_text(f"VITE_API_PORT={self.api_port}\n", encoding="utf-8")

            stdout_log = open(self.log_dir / f"frontend_{timestamp}.log", "w", encoding="utf-8")
            stderr_log = open(self.log_dir / f"frontend_err_{timestamp}.log", "w", encoding="utf-8")

            # --- Placeholder & Warmup Start ---
            from scripts.fixes.frontend_placeholder import PlaceholderServer
            placeholder = PlaceholderServer(self.frontend_port, logger=self.log)
            placeholder.start()

            temp_port = self.frontend_port + 10000
            self.log.info(f"Starting Vite on temporary port {temp_port} for warmup...")
            
            warmup_proc = subprocess.Popen(
                ["npm.cmd", "run", "dev", "--", "--host", "--port", str(temp_port)],
                cwd=str(frontend_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=frontend_env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            # Wait for Vite to be ready
            start_time = time.time()
            is_ready = False
            while time.time() - start_time < 120:  # 2 min timeout
                if is_port_listening(temp_port):
                    is_ready = True
                    break
                if warmup_proc.poll() is not None:
                    self.log.error("Vite warmup process crashed")
                    break
                time.sleep(1)
            
            if is_ready:
                self.log.info(f"Vite is ready on {temp_port}, switching to {self.frontend_port}")
            else:
                self.log.warning("Vite warmup timed out or failed, proceeding with direct start")

            # Stop placeholder & kill warmup proc
            placeholder.stop()
            kill_pid(warmup_proc.pid, logger=self.log)
            # ----------------------------------

            proc = subprocess.Popen(
                ["npm.cmd", "run", "dev", "--", "--host", "--port", str(self.frontend_port)],
                cwd=str(frontend_dir),
                stdout=stdout_log,
                stderr=stderr_log,
                env=frontend_env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            # Production: build → preview
            self.log.info("Building frontend for production...")
            build_result = subprocess.run(
                ["npm.cmd", "run", "build"],
                cwd=str(frontend_dir),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                env=frontend_env,
            )
            if build_result.returncode != 0:
                err_msg = (build_result.stderr or "")[-500:] or "(no stderr output)"
                self.log.error(f"Frontend build failed (rc={build_result.returncode}): {err_msg}")
                # graceful degradation: 이전 빌드가 있으면 그것으로 preview, 없으면 API-only
                if not (frontend_dir / "build").exists():
                    self.log.warning("No previous build found - Frontend unavailable, API-only mode")
                    return None
                self.log.warning("Using previous build for preview")
            else:
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
                env=frontend_env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

        pid_file = self.pid_dir / f"frontend{self.pid_suffix}.pid"
        write_pid_file(pid_file, proc.pid)
        self.log.info(f"Frontend started (PID: {proc.pid})")
        return proc

    # ── 크래시 루프 감지 ─────────────────────────────────────────
    def check_crash_loop(self) -> bool:
        """최근 5분 내 death 이벤트가 3회 이상이면 True 반환.

        Returns:
            True  — 크래시 루프 감지 (백오프 필요)
            False — 정상
        """
        try:
            from app.core.death_log import read_recent_deaths, record_crash_loop
            deaths = read_recent_deaths(window_minutes=5, exclude_causes=["normal_shutdown"])
            count = len(deaths)
            if count >= 3:
                first_err = None
                for d in deaths:
                    if d.get("details"):
                        first_err = d["details"][:200]
                        break
                self.log.warning(
                    f"CRASH LOOP DETECTED: {count} deaths in last 5 minutes"
                )
                record_crash_loop(
                    restart_count=count,
                    window_minutes=5,
                    first_error=first_err,
                )
                return True
        except Exception as e:
            self.log.warning(f"Crash loop check failed: {e}")
        return False

    # ── API 실행 (in-process) ────────────────────────────────────
    def run_api(self):
        self.log.info("Starting API Server in-process...")
        if self.dev:
            self.log.info("Development mode (hot reload disabled for stability)")

        # 크래시 루프 감지 — 백오프
        if self.check_crash_loop():
            death_count = 0
            try:
                from app.core.death_log import read_recent_deaths
                death_count = len(read_recent_deaths(window_minutes=5, exclude_causes=["normal_shutdown"]))
            except Exception:
                pass

            if death_count >= 5:
                self.log.error(
                    f"CRASH LOOP CRITICAL: {death_count} deaths in 5 min. Stopping service."
                )
                sys.exit(2)

            self.log.warning("Crash loop backoff: waiting 30 seconds before restart...")
            time.sleep(30)

        # 환경변수
        os.environ["API_PORT"] = str(self.api_port)
        os.environ["WORKER_AUTO_START"] = "false"
        bootstrap_service_environment(["--admin"] if self.dev else [])

        # 단계별 import (hang 진단용)
        t = time.time()
        self.log.info("Importing app.config...")
        from app.config import settings
        self.log.info(f"  app.config imported ({time.time() - t:.1f}s)")
        if not _log_mode_alignment(self.log, settings.APP_MODE):
            raise RuntimeError("APP_MODE bootstrap drift detected before API startup")

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

        # API 포트 헬스 모니터 — server.run()이 반환하지 않으면서 포트가 죽는 상태 방어
        import threading
        def _port_health_monitor():
            """API 포트가 죽으면 server.should_exit = True 설정하여 프로세스 종료 유도."""
            INITIAL_WAIT = 60  # 서버 시작 대기
            CHECK_INTERVAL = 15
            FAIL_THRESHOLD = 4  # 4회 연속 실패(60초) 시 종료
            time.sleep(INITIAL_WAIT)
            consecutive_failures = 0
            while not server.should_exit:
                if is_port_listening(self.api_port):
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    self.log.warning(
                        f"[HealthMonitor] API port {self.api_port} not listening "
                        f"({consecutive_failures}/{FAIL_THRESHOLD})"
                    )
                    if consecutive_failures >= FAIL_THRESHOLD:
                        self.log.error(
                            f"[HealthMonitor] API port dead for {FAIL_THRESHOLD * CHECK_INTERVAL}s "
                            f"but server.run() still blocking. Triggering shutdown for NSSM restart."
                        )
                        server.should_exit = True
                        # safety: 30초 후에도 종료 안 되면 강제 종료
                        time.sleep(35)
                        self.log.error("[HealthMonitor] Forced exit after 35s timeout")
                        os._exit(1)
                time.sleep(CHECK_INTERVAL)

        monitor_thread = threading.Thread(target=_port_health_monitor, name="api-port-monitor", daemon=True)
        monitor_thread.start()

        # 블로킹 — uvicorn 이벤트 루프 실행
        server.run()

        # server.run() 반환 → exit code로 외부 kill 여부 판단
        # uvicorn 정상 종료 시 0, 외부 kill/강제 종료 시 음수 또는 비0
        exit_code = getattr(server, "exit_code", None)
        self.log.info(f"API Server exited (exit_code={exit_code})")

        # 외부 kill 추정 기록 (death_log에 아직 기록이 없는 경우)
        try:
            from app.core.death_log import read_recent_deaths, record_death
            recent = read_recent_deaths(window_minutes=1)
            has_recent_death = any(
                d.get("cause") not in (None, "") for d in recent
            )
            if not has_recent_death and exit_code is not None and exit_code != 0:
                record_death(
                    cause="external_kill",
                    exit_code=exit_code,
                    details=f"server.run() returned with exit_code={exit_code} (TerminateProcess 추정)",
                )
        except Exception:
            pass

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
    parser.add_argument("--admin", action="store_true", help="Admin mode (port 8001/6101)")
    args = parser.parse_args()

    # main() 진입 즉시 APP_MODE를 고정해 이후 app import가 stale settings를 만들지 않게 한다.
    bootstrap_service_environment(["--admin"] if args.admin else [])
    runner = ServiceRunner(dev=args.admin)
    runner.run()


if __name__ == "__main__":
    main()
