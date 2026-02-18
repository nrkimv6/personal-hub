"""서비스 관리 공통 유틸리티.

service_run.py, browser_workers.py에서 공유하는 프로세스/포트/PID 관리 함수.
"""
import ctypes
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil


# ── Session 0 감지 ──────────────────────────────────────────────
def get_session_id() -> int:
    """현재 프로세스의 Windows Session ID를 반환한다. 실패 시 -1."""
    if sys.platform != "win32":
        return -1
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        session_id = ctypes.c_ulong(0)
        if kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
            return session_id.value
    except Exception:
        pass
    return -1


# ── 포트 유틸 ───────────────────────────────────────────────────
def is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    """TCP 포트가 LISTEN 상태인지 확인한다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        return s.connect_ex((host, port)) == 0


def find_pids_on_port(port: int) -> list[int]:
    """지정 포트에서 LISTEN 중인 프로세스 PID 목록을 반환한다."""
    pids: list[int] = []
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status == "LISTEN" and conn.laddr.port == port:
            if conn.pid and conn.pid not in pids:
                pids.append(conn.pid)
    return pids


# ── 프로세스 유틸 ───────────────────────────────────────────────
def kill_pid(pid: int, timeout: int = 5, logger: logging.Logger | None = None) -> bool:
    """PID를 graceful → force 순서로 종료한다. 성공 시 True."""
    log = logger.info if logger else (lambda m: None)
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
            log(f"PID {pid} ({proc.name()}) terminated gracefully")  # type: ignore[arg-type]
            return True
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
            log(f"PID {pid} force killed")  # type: ignore[arg-type]
            return True
    except psutil.NoSuchProcess:
        return True  # 이미 종료됨
    except (psutil.AccessDenied, PermissionError):
        # 권한 부족 시 taskkill /F fallback (NSSM 서비스 프로세스 등)
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
            if logger:
                logger.info(f"PID {pid} killed via taskkill fallback")
            return True
        except Exception as e2:
            if logger:
                logger.warning(f"Failed to kill PID {pid} via taskkill: {e2}")
            return False
    except Exception as e:
        if logger:
            logger.warning(f"Failed to kill PID {pid}: {e}")
        return False


def is_process_alive(pid: int) -> bool:
    """PID가 살아있는지 확인한다."""
    return psutil.pid_exists(pid)


# ── PID 파일 유틸 ───────────────────────────────────────────────
def read_pid_file(path: Path | str) -> int | None:
    """PID 파일을 읽어 정수를 반환한다. 실패 시 None."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        text = path.read_text().strip()
        return int(text) if text.isdigit() else None
    except Exception:
        return None


def write_pid_file(path: Path | str, pid: int) -> None:
    """PID 파일에 PID를 기록한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="ascii")


def remove_pid_file(path: Path | str) -> None:
    """PID 파일을 삭제한다."""
    path = Path(path)
    if path.exists():
        path.unlink(missing_ok=True)


# ── 로깅 유틸 ───────────────────────────────────────────────────
def setup_service_logger(
    name: str,
    log_path: Path | str,
    level: int = logging.INFO,
) -> logging.Logger:
    """파일 + 콘솔 듀얼 핸들러 로거를 생성한다."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # 파일 핸들러 (append)
    fh = logging.FileHandler(str(log_path), encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 콘솔 핸들러
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger
