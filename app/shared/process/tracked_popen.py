"""subprocess 래퍼 — Popen 호출 시 ProcessRegistry에 자동 등록."""
import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from app.shared.process.registry import ProcessRegistry
from app.shared.process.subprocess_text import with_text_subprocess_defaults

# scripts/services/service_utils.py의 kill_pid를 동적으로 임포트
def kill_pid(pid: int, timeout: int = 5) -> bool:
    """service_utils.kill_pid 위임 래퍼."""
    try:
        scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
        services_dir = str(Path(__file__).resolve().parents[3] / "scripts" / "services")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        if services_dir not in sys.path:
            sys.path.insert(0, services_dir)
        from service_utils import kill_pid as _kill_pid  # type: ignore
        return _kill_pid(pid, timeout)
    except Exception as exc:
        logger.warning("kill_pid 실패 (pid=%s): %s", pid, exc)
        return False

logger = logging.getLogger(__name__)


async def tracked_popen(
    cmd: list,
    role: str = "unknown",
    **kwargs,
) -> subprocess.Popen:
    """subprocess.Popen 실행 후 ProcessRegistry에 자동 등록.

    Args:
        cmd: 실행할 명령어 리스트
        role: 프로세스 역할 (worker, watchdog 등)
        **kwargs: subprocess.Popen에 전달할 추가 인자

    Returns:
        subprocess.Popen 객체
    """
    proc = subprocess.Popen(cmd, **with_text_subprocess_defaults(**kwargs))
    try:
        exe = str(cmd[0]) if cmd else ""
        name = Path(exe).stem if exe else "unknown"
        await ProcessRegistry().register(
            pid=proc.pid,
            ppid=os.getpid(),
            name=name,
            exe=exe,
            role=role,
        )
    except Exception as exc:
        logger.warning("tracked_popen: 레지스트리 등록 실패 (pid=%s): %s", proc.pid, exc)
    return proc


async def tracked_kill(pid: int, timeout: int = 5) -> bool:
    """프로세스를 종료하고 Registry에서 해제.

    Args:
        pid: 종료할 프로세스 ID
        timeout: 대기 시간 (초)

    Returns:
        True: 성공, False: 실패
    """
    await ProcessRegistry().unregister(pid)
    return kill_pid(pid, timeout)


def tracked_popen_sync(
    cmd: list,
    role: str = "unknown",
    **kwargs,
) -> subprocess.Popen:
    """동기 버전 tracked_popen — browser_workers.py facade 등 동기 스크립트용.

    새 이벤트 루프를 생성하여 비동기 등록을 실행.
    Redis 실패 시 경고만 출력하고 Popen 객체를 반환.

    Args:
        cmd: 실행할 명령어 리스트
        role: 프로세스 역할
        **kwargs: subprocess.Popen에 전달할 추가 인자

    Returns:
        subprocess.Popen 객체
    """
    proc = subprocess.Popen(cmd, **with_text_subprocess_defaults(**kwargs))
    try:
        exe = str(cmd[0]) if cmd else ""
        name = Path(exe).stem if exe else "unknown"
        asyncio.run(
            ProcessRegistry().register(
                pid=proc.pid,
                ppid=os.getpid(),
                name=name,
                exe=exe,
                role=role,
            )
        )
    except Exception as exc:
        logger.warning(
            "tracked_popen_sync: 레지스트리 등록 실패 (pid=%s): %s", proc.pid, exc
        )
    return proc
