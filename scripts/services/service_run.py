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
import threading
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (app 패키지 import용)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from scripts.services.service_utils import (
    find_pids_on_port,
    get_session_id,
    is_port_listening,
    is_process_alive,
    kill_pid,
    pick_listener_pid,
    read_pid_file,
    remove_pid_file,
    setup_service_logger,
    write_pid_file,
)

import psutil
from app.core.runtime_fingerprint import get_runtime_fingerprint_snapshot


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
        self._frontend_monitor_thread: threading.Thread | None = None
        self._frontend_monitor_stop = threading.Event()
        self._frontend_restart_lock = threading.Lock()
        self._frontend_state_lock = threading.Lock()
        self._frontend_health = "unknown"
        self._frontend_degraded_reason: str | None = None
        self._frontend_last_build_error_at: float | None = None
        self._frontend_listener_pid: int | None = None
        self._frontend_retry_count = 0
        self._cleaned_up = False

    # ── 메인 실행 흐름 ──────────────────────────────────────────
    def run(self):
        os.environ["PYTHONIOENCODING"] = "utf-8"

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
            if not self.dev:
                self._start_frontend_monitor()
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

    def _frontend_pid_file(self) -> Path:
        return self.pid_dir / f"frontend{self.pid_suffix}.pid"

    def _set_frontend_state(
        self,
        health: str,
        reason: str | None = None,
        pid: int | None = None,
        listener_pid: int | None = None,
    ) -> None:
        with self._frontend_state_lock:
            self._frontend_health = health
            self._frontend_degraded_reason = reason
            self._frontend_listener_pid = listener_pid
            if health == "healthy":
                self._frontend_retry_count = 0

    def _mark_frontend_healthy(self, pid: int | None = None, listener_pid: int | None = None) -> None:
        self._set_frontend_state("healthy", None, pid=pid, listener_pid=listener_pid)

    def _mark_frontend_degraded(
        self,
        reason: str,
        pid: int | None = None,
        listener_pid: int | None = None,
    ) -> None:
        with self._frontend_state_lock:
            self._frontend_health = "degraded"
            self._frontend_degraded_reason = reason
            self._frontend_listener_pid = listener_pid
            if pid is not None:
                self._frontend_listener_pid = listener_pid

    def _mark_frontend_down(self, reason: str) -> None:
        with self._frontend_state_lock:
            self._frontend_health = "down"
            self._frontend_degraded_reason = reason
            self._frontend_listener_pid = None

    def _cleanup_frontend_runtime(self):
        pid_file = self._frontend_pid_file()
        if self._frontend_proc and self._frontend_proc.poll() is None:
            self.log.info(f"Stopping existing Frontend process (PID: {self._frontend_proc.pid})...")
            kill_pid(self._frontend_proc.pid, logger=self.log)
        self._frontend_proc = None

        pid = read_pid_file(pid_file)
        if pid is not None and is_process_alive(pid):
            self.log.info(f"Stopping stored Frontend PID (PID: {pid})...")
            kill_pid(pid, logger=self.log)

        remove_pid_file(pid_file)

        for pid_on_port in find_pids_on_port(self.frontend_port):
            if self._frontend_proc and pid_on_port == self._frontend_proc.pid:
                continue
            self.log.info(f"  Frontend port {self.frontend_port}: killing PID {pid_on_port}")
            kill_pid(pid_on_port, logger=self.log)

    def _wait_for_frontend_listener(self, proc: subprocess.Popen, timeout_seconds: int = 30) -> int | None:
        deadline = time.time() + timeout_seconds
        listener_pid: int | None = None
        while time.time() < deadline:
            listener_pid = pick_listener_pid(self.frontend_port)
            if listener_pid is not None:
                return listener_pid
            if proc.poll() is not None:
                break
            time.sleep(1)
        return listener_pid

    def _sync_frontend_pid_file(self, proc: subprocess.Popen) -> int | None:
        pid_file = self._frontend_pid_file()
        listener_pid = self._wait_for_frontend_listener(proc)
        pid_to_record = listener_pid or (proc.pid if proc.poll() is None else None)
        if pid_to_record is not None:
            write_pid_file(pid_file, pid_to_record)
        else:
            remove_pid_file(pid_file)
        return pid_to_record

    def _frontend_is_healthy(self) -> tuple[bool, str | None]:
        pid_file = self._frontend_pid_file()
        pid = read_pid_file(pid_file)
        listener_pid = pick_listener_pid(self.frontend_port)

        if pid is None:
            if listener_pid is not None:
                return False, "pid_file_missing"
            return False, "port_not_listening"

        if not is_process_alive(pid):
            if listener_pid is not None:
                return False, "pid_stale"
            return False, "process_not_running"

        if listener_pid is None:
            return False, "port_not_listening"

        if listener_pid != pid:
            return False, "listener_pid_drift"

        return True, None

    def _start_frontend_monitor(self) -> None:
        if self.dev or self._frontend_monitor_thread is not None:
            return

        def _monitor_loop():
            initial_delay = 20
            retry_backoff = 30
            max_backoff = 300
            time.sleep(initial_delay)

            while not self._frontend_monitor_stop.is_set():
                healthy, reason = self._frontend_is_healthy()
                if healthy:
                    listener_pid = pick_listener_pid(self.frontend_port)
                    stored_pid = read_pid_file(self._frontend_pid_file())
                    self._mark_frontend_healthy(pid=stored_pid, listener_pid=listener_pid)
                    retry_backoff = 30
                    self._frontend_retry_count = 0
                    time.sleep(30)
                    continue

                if reason:
                    self._mark_frontend_degraded(reason, pid=read_pid_file(self._frontend_pid_file()))

                if not self._frontend_restart_lock.acquire(blocking=False):
                    time.sleep(10)
                    continue

                try:
                    self._frontend_retry_count += 1
                    self.log.warning(
                        f"Frontend unhealthy ({reason or 'unknown'}) — retry #{self._frontend_retry_count}"
                    )
                    self._cleanup_frontend_runtime()
                    proc = self.start_frontend()
                    self._frontend_proc = proc
                    if proc is not None:
                        healthy, next_reason = self._frontend_is_healthy()
                        if healthy:
                            listener_pid = pick_listener_pid(self.frontend_port)
                            stored_pid = read_pid_file(self._frontend_pid_file())
                            self._mark_frontend_healthy(pid=stored_pid, listener_pid=listener_pid)
                            retry_backoff = 30
                            self._frontend_retry_count = 0
                        else:
                            self._mark_frontend_degraded(next_reason or "frontend_restart_failed")
                            retry_backoff = min(max_backoff, retry_backoff * 2)
                    else:
                        retry_backoff = min(max_backoff, retry_backoff * 2)
                finally:
                    self._frontend_restart_lock.release()

                time.sleep(retry_backoff)

        self._frontend_monitor_thread = threading.Thread(
            target=_monitor_loop,
            name="frontend-health-monitor",
            daemon=True,
        )
        self._frontend_monitor_thread.start()

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
        self._cleanup_frontend_runtime()
        frontend_dir = PROJECT_ROOT / "frontend"
        timestamp = time.strftime("%Y%m%d_%H%M%S")

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
            subprocess.run(["npm.cmd", "install"], cwd=str(frontend_dir), check=False,
                           encoding="utf-8", errors="replace")
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
            os.environ["VITE_API_PORT"] = str(self.api_port)

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

            try:
                proc = subprocess.Popen(
                    ["npm.cmd", "run", "dev", "--", "--host", "--port", str(self.frontend_port)],
                    cwd=str(frontend_dir),
                    stdout=stdout_log,
                    stderr=stderr_log,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception as e:
                self._mark_frontend_down(f"dev_preview_launch_failed:{e.__class__.__name__}")
                self.log.error(f"Frontend dev launch failed: {e}", exc_info=True)
                return None
            listener_pid = self._sync_frontend_pid_file(proc)
            if listener_pid is None:
                self._mark_frontend_degraded("dev_preview_not_listening", pid=proc.pid)
            else:
                self._mark_frontend_healthy(pid=proc.pid, listener_pid=listener_pid)
        else:
            # Production: build → preview
            build_dir = frontend_dir / "build"
            self.log.info("Building frontend for production...")
            build_result = subprocess.run(
                ["npm.cmd", "run", "build"],
                cwd=str(frontend_dir),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
            build_failed = build_result.returncode != 0
            if build_failed:
                err_msg = (build_result.stderr or build_result.stdout or "")[-500:] or "(no output)"
                self._frontend_last_build_error_at = time.time()
                self.log.error(f"Frontend build failed (rc={build_result.returncode}): {err_msg}")
                # graceful degradation: 이전 빌드가 없으면 API-only, 있으면 fallback preview
                if not build_dir.exists():
                    self._mark_frontend_down("build_failed")
                    self.log.warning("No previous build found — Frontend unavailable, API-only mode")
                    return None
                self._mark_frontend_degraded("build_failed_with_fallback")
                self.log.warning("Using previous build for preview")
            else:
                self.log.info("Frontend build completed")

            # .env.local 제거 (production에서 dev 설정 방지)
            env_local = frontend_dir / ".env.local"
            if env_local.exists():
                env_local.unlink()

            stdout_log = open(self.log_dir / f"frontend_{timestamp}.log", "w", encoding="utf-8")
            stderr_log = open(self.log_dir / f"frontend_err_{timestamp}.log", "w", encoding="utf-8")

            try:
                proc = subprocess.Popen(
                    ["npm.cmd", "run", "preview", "--", "--host", "--port", str(self.frontend_port)],
                    cwd=str(frontend_dir),
                    stdout=stdout_log,
                    stderr=stderr_log,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception as e:
                self._mark_frontend_down(f"preview_launch_failed:{e.__class__.__name__}")
                self.log.error(f"Frontend preview launch failed: {e}", exc_info=True)
                return None
            listener_pid = self._sync_frontend_pid_file(proc)
            if listener_pid is None:
                self._mark_frontend_degraded(
                    "build_failed_with_fallback" if build_failed else "preview_not_listening",
                    pid=proc.pid,
                )
            elif build_failed:
                self._mark_frontend_degraded("build_failed_with_fallback", pid=proc.pid, listener_pid=listener_pid)
            else:
                self._mark_frontend_healthy(pid=proc.pid, listener_pid=listener_pid)

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
        os.environ["APP_MODE"] = self.app_mode

        # 단계별 import (hang 진단용)
        t = time.time()
        self.log.info(f"Import context: cwd={os.getcwd()} | sys.path[0]={sys.path[0]} | __file__={__file__}")
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
        self._frontend_monitor_stop.set()
        if self._frontend_monitor_thread and self._frontend_monitor_thread.is_alive():
            self._frontend_monitor_thread.join(timeout=2)

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

    runner = ServiceRunner(dev=args.admin)
    runner.run()


if __name__ == "__main__":
    main()
