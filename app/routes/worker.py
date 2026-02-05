"""
워커 관리 API 엔드포인트
모니터링 워커 프로세스를 관리하기 위한 API를 제공합니다.

워커 시작/중지/재시작은 Redis를 통해 Session 1의 리스너에 명령을 전달합니다.
API 서버(Session 0)에서 직접 워커 프로세스를 생성하지 않습니다.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import json
import sys
import os
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
    global_pause: bool = False
    paused_at: Optional[str] = None
    # 브라우저 상태 (graceful degradation)
    browser_available: bool = False
    browser_error: Optional[str] = None
    browser_recovery_attempts: int = 0
    browser_permanently_failed: bool = False


class BrowserStatusResponse(BaseModel):
    """워커 브라우저 상태 응답"""
    available: bool
    error: Optional[str] = None
    recovery_attempts: int = 0
    permanently_failed: bool = False
    last_heartbeat: Optional[str] = None


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
            SELECT pid, status, start_time, last_heartbeat, active_tasks, error_message,
                   global_pause, paused_at,
                   browser_available, browser_error, browser_recovery_attempts, browser_permanently_failed
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
                "error_message": result[5],
                "global_pause": bool(result[6]) if result[6] is not None else False,
                "paused_at": result[7],
                # 브라우저 상태
                "browser_available": bool(result[8]) if result[8] is not None else False,
                "browser_error": result[9],
                "browser_recovery_attempts": result[10] or 0,
                "browser_permanently_failed": bool(result[11]) if result[11] is not None else False
            }
        return {
            "pid": None,
            "status": "not_started",
            "start_time": None,
            "last_heartbeat": None,
            "active_tasks": 0,
            "error_message": None,
            "global_pause": False,
            "paused_at": None,
            "browser_available": False,
            "browser_error": None,
            "browser_recovery_attempts": 0,
            "browser_permanently_failed": False
        }
    except Exception as e:
        logger.error(f"워커 상태 조회 실패: {str(e)}")
        return {
            "pid": None,
            "status": "unknown",
            "start_time": None,
            "last_heartbeat": None,
            "active_tasks": 0,
            "error_message": str(e),
            "global_pause": False,
            "paused_at": None,
            "browser_available": False,
            "browser_error": None,
            "browser_recovery_attempts": 0,
            "browser_permanently_failed": False
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


# ============= Redis Worker Command =============

REDIS_WORKER_COMMANDS_KEY = "worker:commands"
REDIS_WORKER_RESULTS_KEY = "worker:command_results"
REDIS_COMMAND_RESULT_TIMEOUT = 15  # 결과 대기 타임아웃 (초)


async def _send_worker_command(action: str) -> dict:
    """Redis를 통해 워커 명령을 전송하고 결과를 대기합니다.

    Session 1에서 실행 중인 worker-command-listener가 명령을 수신하고 실행합니다.

    Args:
        action: 워커 명령 (start, stop, restart)

    Returns:
        dict: {success: bool, message: str}
    """
    from app.shared.redis.client import RedisClient

    redis_client = await RedisClient.get_client()
    if not redis_client:
        return {"success": False, "message": "Redis 연결 없음. 워커는 Session 1에서 수동 관리하세요: browser-workers.ps1 -Action " + action}

    command = json.dumps({
        "action": action,
        "timestamp": datetime.now().isoformat(),
        "source": "api",
    })

    try:
        # 이전 결과 비우기
        await redis_client.delete(REDIS_WORKER_RESULTS_KEY)

        # 명령 전송
        await redis_client.lpush(REDIS_WORKER_COMMANDS_KEY, command)
        logger.info(f"[WorkerAPI] Redis 워커 명령 전송: {action}")

        # 결과 대기 (BRPOP - 블로킹)
        result = await redis_client.brpop(REDIS_WORKER_RESULTS_KEY, timeout=REDIS_COMMAND_RESULT_TIMEOUT)

        if result:
            _, result_data = result
            result_json = json.loads(result_data) if isinstance(result_data, str) else json.loads(result_data.decode())
            logger.info(f"[WorkerAPI] 워커 명령 결과: {result_json}")
            return result_json
        else:
            return {"success": False, "message": f"명령 '{action}' 전송됨, 리스너 응답 타임아웃 ({REDIS_COMMAND_RESULT_TIMEOUT}초). 리스너가 실행 중인지 확인하세요."}

    except Exception as e:
        logger.error(f"[WorkerAPI] Redis 워커 명령 전송 실패: {e}")
        return {"success": False, "message": f"Redis 명령 전송 실패: {str(e)}"}


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
    """워커 프로세스를 시작합니다. (Redis → Session 1 리스너)"""
    # 이미 실행 중인지 확인
    status_data = get_worker_status_from_db()
    pid = status_data.get("pid")

    if pid and is_process_running(pid):
        return WorkerActionResponse(
            success=False,
            message=f"워커가 이미 실행 중입니다 (PID: {pid})",
            pid=pid
        )

    result = await _send_worker_command("start")
    return WorkerActionResponse(
        success=result["success"],
        message=result["message"],
        pid=result.get("pid")
    )


@router.post("/stop", response_model=WorkerActionResponse)
async def stop_worker():
    """워커 프로세스를 중지합니다. (Redis → Session 1 리스너)"""
    status_data = get_worker_status_from_db()
    pid = status_data.get("pid")

    if not pid or not is_process_running(pid):
        return WorkerActionResponse(
            success=False,
            message="실행 중인 워커가 없습니다",
            pid=None
        )

    result = await _send_worker_command("stop")
    return WorkerActionResponse(
        success=result["success"],
        message=result["message"],
        pid=result.get("pid")
    )


@router.post("/restart", response_model=WorkerActionResponse)
async def restart_worker():
    """워커 프로세스를 재시작합니다. (Redis → Session 1 리스너)"""
    result = await _send_worker_command("restart")
    return WorkerActionResponse(
        success=result["success"],
        message=result["message"],
        pid=result.get("pid")
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


@router.post("/pause", response_model=WorkerActionResponse)
async def pause_monitoring():
    """전체 모니터링을 일시중지합니다.

    워커 프로세스는 계속 실행되지만 새로운 스케줄 처리와
    기존 모니터링 체크를 일시적으로 중단합니다.
    """
    db = SessionLocal()
    try:
        # 현재 상태 확인
        result = db.execute(text(
            "SELECT global_pause FROM worker_status WHERE id = 1"
        )).fetchone()

        if result and result[0]:
            return WorkerActionResponse(
                success=False,
                message="모니터링이 이미 일시중지 상태입니다",
                pid=None
            )

        # 일시중지 상태로 변경
        db.execute(text("""
            UPDATE worker_status
            SET global_pause = 1, paused_at = datetime('now', 'localtime'), updated_at = datetime('now', 'localtime')
            WHERE id = 1
        """))
        db.commit()

        logger.info("전체 모니터링 일시중지됨")

        return WorkerActionResponse(
            success=True,
            message="전체 모니터링이 일시중지되었습니다",
            pid=None
        )
    except Exception as e:
        db.rollback()
        logger.error(f"모니터링 일시중지 실패: {str(e)}")
        return WorkerActionResponse(
            success=False,
            message=f"일시중지 실패: {str(e)}",
            pid=None
        )
    finally:
        db.close()


@router.post("/resume", response_model=WorkerActionResponse)
async def resume_monitoring():
    """일시중지된 모니터링을 재개합니다."""
    db = SessionLocal()
    try:
        # 현재 상태 확인
        result = db.execute(text(
            "SELECT global_pause FROM worker_status WHERE id = 1"
        )).fetchone()

        if result and not result[0]:
            return WorkerActionResponse(
                success=False,
                message="모니터링이 이미 실행 중입니다",
                pid=None
            )

        # 재개 상태로 변경
        db.execute(text("""
            UPDATE worker_status
            SET global_pause = 0, paused_at = NULL, updated_at = datetime('now', 'localtime')
            WHERE id = 1
        """))

        # running/queued 상태인 활성화된 스케줄을 pending으로 리셋하여 워커가 다시 시작하도록 함
        reset_result = db.execute(text("""
            UPDATE monitor_schedules
            SET run_status = 'pending', is_active = 0
            WHERE is_enabled = 1 AND run_status IN ('running', 'queued')
        """))
        reset_count = reset_result.rowcount

        db.commit()

        logger.info(f"전체 모니터링 재개됨 (리셋된 스케줄: {reset_count}개)")

        return WorkerActionResponse(
            success=True,
            message="전체 모니터링이 재개되었습니다",
            pid=None
        )
    except Exception as e:
        db.rollback()
        logger.error(f"모니터링 재개 실패: {str(e)}")
        return WorkerActionResponse(
            success=False,
            message=f"재개 실패: {str(e)}",
            pid=None
        )
    finally:
        db.close()


@router.get("/browser-status", response_model=BrowserStatusResponse)
async def get_browser_status():
    """워커의 브라우저 서비스 상태를 조회합니다.

    브라우저 서비스가 사용 가능한지, 오류가 있는지,
    복구 시도 횟수와 복구 포기 상태를 반환합니다.
    """
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT browser_available, browser_error, browser_recovery_attempts,
                   browser_permanently_failed, last_heartbeat
            FROM worker_status WHERE id = 1
        """)).fetchone()

        if not result:
            return BrowserStatusResponse(
                available=False,
                error="워커 상태 정보 없음",
                recovery_attempts=0,
                permanently_failed=False,
                last_heartbeat=None
            )

        return BrowserStatusResponse(
            available=bool(result[0]) if result[0] is not None else False,
            error=result[1],
            recovery_attempts=result[2] or 0,
            permanently_failed=bool(result[3]) if result[3] is not None else False,
            last_heartbeat=result[4]
        )
    except Exception as e:
        logger.error(f"브라우저 상태 조회 실패: {str(e)}")
        return BrowserStatusResponse(
            available=False,
            error=f"조회 실패: {str(e)}",
            recovery_attempts=0,
            permanently_failed=False,
            last_heartbeat=None
        )
    finally:
        db.close()
