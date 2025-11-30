"""
워커 관리 API 엔드포인트
모니터링 워커 프로세스를 관리하기 위한 API를 제공합니다.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import subprocess
import sys
import os
import signal
import psutil
from pathlib import Path

from app.config import settings, logger
from app.database import SessionLocal
from sqlalchemy import text

router = APIRouter(prefix="/worker", tags=["Worker Management"])


# ============= Schemas =============

class WorkerStatusResponse(BaseModel):
    """워커 상태 응답"""
    pid: Optional[int] = None
    status: str
    start_time: Optional[str] = None
    last_heartbeat: Optional[str] = None
    active_tasks: int = 0
    error_message: Optional[str] = None
    uptime_seconds: Optional[int] = None
    memory_usage_mb: Optional[float] = None


class WorkerActionResponse(BaseModel):
    """워커 작업 응답"""
    success: bool
    message: str
    pid: Optional[int] = None


class WorkerLogsResponse(BaseModel):
    """워커 로그 응답"""
    logs: List[str]
    total_lines: int
    file_path: str


# ============= Helper Functions =============

def get_worker_status_from_db() -> dict:
    """데이터베이스에서 워커 상태를 조회합니다."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT pid, status, start_time, last_heartbeat, active_tasks, error_message
            FROM worker_status
            WHERE id = 1
        """)).fetchone()

        if result:
            return {
                "pid": result[0],
                "status": result[1],
                "start_time": result[2],
                "last_heartbeat": result[3],
                "active_tasks": result[4],
                "error_message": result[5]
            }
        return {
            "pid": None,
            "status": "not_started",
            "start_time": None,
            "last_heartbeat": None,
            "active_tasks": 0,
            "error_message": None
        }
    except Exception as e:
        logger.error(f"워커 상태 조회 실패: {str(e)}")
        return {
            "pid": None,
            "status": "unknown",
            "start_time": None,
            "last_heartbeat": None,
            "active_tasks": 0,
            "error_message": str(e)
        }
    finally:
        db.close()


def is_process_running(pid: int) -> bool:
    """프로세스가 실행 중인지 확인합니다."""
    if pid is None:
        return False
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def get_process_memory(pid: int) -> Optional[float]:
    """프로세스의 메모리 사용량을 MB 단위로 반환합니다."""
    try:
        process = psutil.Process(pid)
        memory_info = process.memory_info()
        return memory_info.rss / (1024 * 1024)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def calculate_uptime(start_time_str: str) -> Optional[int]:
    """시작 시간부터 현재까지의 시간(초)을 계산합니다."""
    if not start_time_str:
        return None
    try:
        start_time = datetime.fromisoformat(start_time_str)
        uptime = datetime.now() - start_time
        return int(uptime.total_seconds())
    except Exception:
        return None


# ============= Global Worker Process Reference =============

_worker_process: Optional[subprocess.Popen] = None


def get_worker_process() -> Optional[subprocess.Popen]:
    """전역 워커 프로세스 참조를 반환합니다."""
    global _worker_process
    return _worker_process


def set_worker_process(process: Optional[subprocess.Popen]):
    """전역 워커 프로세스 참조를 설정합니다."""
    global _worker_process
    _worker_process = process


# ============= API Endpoints =============

@router.get("/status", response_model=WorkerStatusResponse)
async def get_worker_status():
    """워커 프로세스의 현재 상태를 조회합니다."""
    status_data = get_worker_status_from_db()

    # 프로세스 실행 상태 확인
    pid = status_data.get("pid")
    if pid and not is_process_running(pid):
        # DB에 있지만 프로세스가 실행 중이 아닌 경우
        status_data["status"] = "crashed"
        status_data["error_message"] = f"프로세스(PID: {pid})가 비정상 종료됨"

    # 추가 정보
    if pid and is_process_running(pid):
        status_data["memory_usage_mb"] = get_process_memory(pid)
        status_data["uptime_seconds"] = calculate_uptime(status_data.get("start_time"))

    return WorkerStatusResponse(**status_data)


@router.post("/start", response_model=WorkerActionResponse)
async def start_worker():
    """워커 프로세스를 시작합니다."""
    # 이미 실행 중인지 확인
    status_data = get_worker_status_from_db()
    pid = status_data.get("pid")

    if pid and is_process_running(pid):
        return WorkerActionResponse(
            success=False,
            message=f"워커가 이미 실행 중입니다 (PID: {pid})",
            pid=pid
        )

    try:
        # 워커 프로세스 시작
        worker_script = Path(__file__).parent.parent / "worker" / "monitor_worker.py"

        # Python 인터프리터 경로
        python_path = sys.executable

        # 워커 프로세스 시작 (백그라운드)
        process = subprocess.Popen(
            [python_path, "-m", "app.worker.monitor_worker"],
            cwd=str(Path(__file__).parent.parent.parent),  # 프로젝트 루트
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True  # 새 세션에서 실행 (부모 프로세스 종료 시에도 계속 실행)
        )

        # 전역 참조 저장
        set_worker_process(process)

        logger.info(f"워커 프로세스 시작됨 (PID: {process.pid})")

        return WorkerActionResponse(
            success=True,
            message=f"워커 프로세스가 시작되었습니다",
            pid=process.pid
        )

    except Exception as e:
        logger.error(f"워커 시작 실패: {str(e)}", exc_info=True)
        return WorkerActionResponse(
            success=False,
            message=f"워커 시작 실패: {str(e)}",
            pid=None
        )


@router.post("/stop", response_model=WorkerActionResponse)
async def stop_worker():
    """워커 프로세스를 중지합니다."""
    status_data = get_worker_status_from_db()
    pid = status_data.get("pid")

    if not pid or not is_process_running(pid):
        return WorkerActionResponse(
            success=False,
            message="실행 중인 워커가 없습니다",
            pid=None
        )

    try:
        # 프로세스에 종료 시그널 전송
        process = psutil.Process(pid)

        # 우선 SIGTERM 전송 (graceful shutdown)
        if sys.platform == 'win32':
            process.terminate()
        else:
            os.kill(pid, signal.SIGTERM)

        # 최대 10초 대기
        try:
            process.wait(timeout=10)
        except psutil.TimeoutExpired:
            # 강제 종료
            logger.warning(f"워커가 정상 종료되지 않아 강제 종료합니다 (PID: {pid})")
            process.kill()
            process.wait(timeout=5)

        # 전역 참조 정리
        set_worker_process(None)

        logger.info(f"워커 프로세스 종료됨 (PID: {pid})")

        return WorkerActionResponse(
            success=True,
            message=f"워커 프로세스가 종료되었습니다 (PID: {pid})",
            pid=pid
        )

    except psutil.NoSuchProcess:
        return WorkerActionResponse(
            success=True,
            message="워커 프로세스가 이미 종료되었습니다",
            pid=pid
        )
    except Exception as e:
        logger.error(f"워커 종료 실패: {str(e)}", exc_info=True)
        return WorkerActionResponse(
            success=False,
            message=f"워커 종료 실패: {str(e)}",
            pid=pid
        )


@router.post("/restart", response_model=WorkerActionResponse)
async def restart_worker():
    """워커 프로세스를 재시작합니다."""
    # 먼저 중지
    stop_result = await stop_worker()

    # 잠시 대기
    import asyncio
    await asyncio.sleep(2)

    # 시작
    start_result = await start_worker()

    if start_result.success:
        return WorkerActionResponse(
            success=True,
            message="워커 프로세스가 재시작되었습니다",
            pid=start_result.pid
        )
    else:
        return WorkerActionResponse(
            success=False,
            message=f"워커 재시작 실패: {start_result.message}",
            pid=None
        )


@router.get("/logs", response_model=WorkerLogsResponse)
async def get_worker_logs(lines: int = 100, filter: Optional[str] = None):
    """워커 로그를 조회합니다."""
    log_dir = Path("logs")

    # 가장 최근 워커 로그 파일 찾기
    worker_logs = list(log_dir.glob("worker_*.log"))

    if not worker_logs:
        return WorkerLogsResponse(
            logs=[],
            total_lines=0,
            file_path=""
        )

    # 가장 최근 로그 파일
    latest_log = max(worker_logs, key=lambda p: p.stat().st_mtime)

    try:
        with open(latest_log, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()

        # 필터 적용
        if filter:
            filtered_lines = [line for line in all_lines if filter.lower() in line.lower()]
        else:
            filtered_lines = all_lines

        # 마지막 N줄
        result_lines = filtered_lines[-lines:] if len(filtered_lines) > lines else filtered_lines

        return WorkerLogsResponse(
            logs=[line.strip() for line in result_lines],
            total_lines=len(all_lines),
            file_path=str(latest_log)
        )

    except Exception as e:
        logger.error(f"로그 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"로그 조회 실패: {str(e)}")


@router.get("/health")
async def check_worker_health():
    """워커의 상태를 상세히 확인합니다."""
    status_data = get_worker_status_from_db()
    pid = status_data.get("pid")
    last_heartbeat = status_data.get("last_heartbeat")

    health = {
        "is_running": False,
        "is_healthy": False,
        "details": {}
    }

    if pid and is_process_running(pid):
        health["is_running"] = True
        health["details"]["pid"] = pid
        health["details"]["memory_mb"] = get_process_memory(pid)

        # 하트비트 확인 (30초 이내면 정상)
        if last_heartbeat:
            try:
                heartbeat_time = datetime.fromisoformat(last_heartbeat)
                seconds_since_heartbeat = (datetime.now() - heartbeat_time).total_seconds()
                health["details"]["seconds_since_heartbeat"] = int(seconds_since_heartbeat)
                health["is_healthy"] = seconds_since_heartbeat < 30
            except Exception:
                health["is_healthy"] = False
    else:
        health["details"]["status"] = status_data.get("status", "unknown")
        if status_data.get("error_message"):
            health["details"]["error"] = status_data["error_message"]

    return health
