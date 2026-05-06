"""서비스 관리 공통 유틸리티.

service_run.py, browser_workers.py에서 공유하는 프로세스/포트/PID 관리 함수.
"""
import asyncio
import ctypes
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

# 프로젝트 루트를 sys.path에 추가 (ProcessRegistry 임포트용)
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent  # scripts/services/ → scripts/ → project root
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── Session 0 감지 ──────────────────────────────────────────────
def get_session_id(pid: int | None = None) -> int:
    """Windows Session ID를 반환한다. 실패 시 -1."""
    if sys.platform != "win32":
        return -1
    target_pid = os.getpid() if pid is None else pid
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        session_id = ctypes.c_ulong(0)
        if kernel32.ProcessIdToSessionId(target_pid, ctypes.byref(session_id)):
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


def pick_listener_pid(port: int, prefer_name: str = "node.exe") -> int | None:
    """지정 포트의 LISTEN PID 중 우선순위 1개를 선택한다.

    우선순위:
    1) 현재 세션과 동일한 PID
    2) 프로세스명이 prefer_name과 일치
    3) create_time이 더 최근인 PID
    """
    pids = find_pids_on_port(port)
    if not pids:
        return None
    if len(pids) == 1:
        return pids[0]

    current_session = get_session_id()
    candidates: list[tuple[int, bool, bool, float]] = []
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            name = (proc.name() or "").lower()
            matched = name == prefer_name.lower()
            same_session = current_session != -1 and get_session_id(pid) == current_session
            create_time = proc.create_time()
            candidates.append((pid, same_session, matched, create_time))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if not candidates:
        return pids[0]

    candidates.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)
    return candidates[0][0]


def describe_listener(port: int) -> dict[str, str | int | None]:
    """지정 포트 리스너의 메타데이터를 구조화해 반환한다."""
    listener_pid = pick_listener_pid(port)
    metadata: dict[str, str | int | None] = {
        "port": port,
        "pid": listener_pid,
        "name": None,
        "owner": None,
        "owner_error": None,
        "cmdline": None,
        "exe": None,
    }
    if listener_pid is None:
        return metadata

    try:
        proc = psutil.Process(listener_pid)
        metadata["name"] = proc.name()
        try:
            metadata["owner"] = proc.username()
        except Exception as exc:
            metadata["owner_error"] = f"{type(exc).__name__}: {exc}"

        try:
            cmdline = " ".join(proc.cmdline() or [])
            metadata["cmdline"] = cmdline or None
        except Exception:
            pass

        try:
            metadata["exe"] = proc.exe() or None
        except Exception:
            pass
    except (psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
        metadata["owner_error"] = f"{type(exc).__name__}: {exc}"

    return metadata


def format_listener_metadata(
    metadata: dict[str, str | int | None],
    *,
    include_port: bool = True,
    max_cmdline_chars: int = 200,
) -> str:
    """listener 메타데이터를 짧은 한 줄로 렌더링한다."""
    pieces: list[str] = []
    field_order = ["port", "pid", "name", "owner", "owner_error", "exe", "cmdline"] if include_port else [
        "pid",
        "name",
        "owner",
        "owner_error",
        "exe",
        "cmdline",
    ]
    for key in field_order:
        value = metadata.get(key)
        if value in (None, ""):
            continue
        rendered = str(value)
        if key == "cmdline" and len(rendered) > max_cmdline_chars:
            rendered = f"{rendered[:max_cmdline_chars]}..."
        pieces.append(f"{key}={rendered}")
    return ", ".join(pieces) if pieces else "no-listener-metadata"


def classify_frontend_failure(*parts: Any) -> str:
    """frontend build/restart 출력으로 failure class를 정규화한다."""
    text = "\n".join(str(part or "") for part in parts).lower()
    if any(
        token in text
        for token in (
            "access denied",
            "access is denied",
            "permission denied",
            "eperm",
            "eacces",
            "file is being used by another process",
            "resource busy",
            "another process",
            "operation not permitted",
        )
    ):
        return "build_lock_permission"
    if any(
        token in text
        for token in (
            "cannot find module",
            "missing script",
            "not recognized as an internal or external command",
            "vite.cmd",
            "node_modules missing",
            "vite binary missing",
        )
    ):
        return "dependency_failure"
    if any(token in text for token in ("port ", "already in use", "eaddrinuse")):
        return "listener_port_collision"
    return "other"


# ── 프로세스 유틸 ───────────────────────────────────────────────
def _unregister_pid_safe(pid: int) -> None:
    """ProcessRegistry에서 pid를 안전하게 해제 (실패 시 무시)."""
    try:
        from app.shared.process.registry import ProcessRegistry
        asyncio.run(ProcessRegistry().unregister(pid))
    except Exception:
        pass


def kill_pid(pid: int, timeout: int = 5, logger: logging.Logger | None = None) -> bool:
    """PID를 graceful → force 순서로 종료한다. 성공 시 True."""
    log = logger.info if logger else (lambda m: None)
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
            log(f"PID {pid} ({proc.name()}) terminated gracefully")  # type: ignore[arg-type]
            _unregister_pid_safe(pid)
            return True
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
            log(f"PID {pid} force killed")  # type: ignore[arg-type]
            _unregister_pid_safe(pid)
            return True
    except psutil.NoSuchProcess:
        _unregister_pid_safe(pid)
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
            _unregister_pid_safe(pid)
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
    log_dir: Path | str,
    level: int = logging.INFO,
) -> logging.Logger:
    """파일 + 콘솔 듀얼 핸들러 로거를 생성한다.

    Args:
        name: 로거 이름 (파일명 접두사로도 사용)
        log_dir: 로그 디렉토리 경로
        level: 로깅 레벨
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{name}_{timestamp}.log"

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
