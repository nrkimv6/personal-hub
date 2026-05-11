"""
워커 관리 API 엔드포인트
모니터링 워커 프로세스를 관리하기 위한 API를 제공합니다.

워커 시작/중지/재시작은 Redis를 통해 Session 1의 리스너에 명령을 전달합니다.
API 서버(Session 0)에서 직접 워커 프로세스를 생성하지 않습니다.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime
import json
import sys
import os
import psutil
import uuid
from pathlib import Path

from app.config import settings, logger
from app.database import SessionLocal
from sqlalchemy import text
from app.shared.worker.health_redis import WorkerHealthRedis, check_pid_alive

router = APIRouter(prefix="/worker", tags=["Worker Management"])


# ============= Schemas =============

class WorkerStatusResponse(BaseModel):
    """워커 상태 응답"""
    pid: Optional[int] = None
    status: str
    started_at: Optional[str] = None
    last_heartbeat: Optional[str] = None
    active_tasks: int = 0
    error_message: Optional[str] = None
    uptime_seconds: Optional[int] = None
    memory_usage_mb: Optional[float] = None
    global_pause: bool = False
    paused_at: Optional[str] = None
    active_tabs: int = 0
    browser_contexts: int = 0


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
    status: Optional[str] = None
    command_id: Optional[str] = None


class WorkerLogsResponse(BaseModel):
    """워커 로그 응답"""
    logs: List[str]
    total_lines: int
    file_path: str


# ============= Helper Functions =============

def _to_iso_timestamp(value):
    """DB timestamp 값을 ISO 문자열 또는 원본 문자열로 정규화합니다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass
    return str(value)


def calculate_uptime(start_time_value: Any) -> Optional[int]:
    """시작 시간부터 현재까지의 시간(초)을 계산합니다."""
    if not start_time_value:
        return None
    try:
        if isinstance(start_time_value, datetime):
            start_time = start_time_value
        else:
            start_time = datetime.fromisoformat(str(start_time_value))
        now = datetime.now(start_time.tzinfo) if start_time.tzinfo else datetime.now()
        uptime = now - start_time
        return max(0, int(uptime.total_seconds()))
    except Exception:
        return None


def get_worker_status_from_db() -> dict:
    """데이터베이스에서 워커 상태를 조회합니다."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT pid, status, active_tasks, last_heartbeat, memory_usage_mb,
                   started_at, active_tabs, browser_contexts, global_pause, paused_at
            FROM worker_status
            WHERE id = 1
        """)).mappings().first()

        if result:
            redis_health = WorkerHealthRedis.check("naver")
            last_heartbeat = redis_health["updated_at"] if redis_health else None
            started_at = _to_iso_timestamp(result["started_at"])
            paused_at = _to_iso_timestamp(result["paused_at"])
            uptime_seconds = calculate_uptime(result["started_at"])
            return {
                "pid": result["pid"],
                "status": result["status"],
                "active_tasks": result["active_tasks"] or 0,
                "last_heartbeat": last_heartbeat,
                "memory_usage_mb": result["memory_usage_mb"],
                "started_at": started_at,
                "uptime_seconds": uptime_seconds,
                "active_tabs": result["active_tabs"] or 0,
                "browser_contexts": result["browser_contexts"] or 0,
                "global_pause": bool(result["global_pause"]) if result["global_pause"] is not None else False,
                "paused_at": paused_at,
                "error_message": None,
            }
        return {
            "pid": None,
            "status": "not_started",
            "active_tasks": 0,
            "last_heartbeat": None,
            "memory_usage_mb": None,
            "started_at": None,
            "uptime_seconds": None,
            "active_tabs": 0,
            "browser_contexts": 0,
            "global_pause": False,
            "paused_at": None,
            "error_message": None,
        }
    except Exception as e:
        logger.error(f"워커 상태 조회 실패: {str(e)}")
        return {
            "pid": None,
            "status": "unknown",
            "active_tasks": 0,
            "last_heartbeat": None,
            "memory_usage_mb": None,
            "started_at": None,
            "uptime_seconds": None,
            "active_tabs": 0,
            "browser_contexts": 0,
            "global_pause": False,
            "paused_at": None,
            "error_message": str(e),
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


# ============= Redis Worker Command =============

REDIS_WORKER_COMMANDS_KEY = "worker:commands"
REDIS_WORKER_RESULTS_KEY = "worker:command_results"


def _manual_worker_command_hint(action: str, **options: Any) -> str:
    command = f"browser-workers.ps1 -Action {action}"
    if action == "restart-frontend" and bool(options.get("public")):
        command += " -Public"
    elif action == "restart-frontend":
        command += " [-Public]"
    return command


async def _send_worker_command(action: str, **options: Any) -> dict:
    """Redis를 통해 워커 명령을 전송하고 command id를 즉시 반환합니다.

    Session 1에서 실행 중인 worker-command-listener가 명령을 수신하고 실행합니다.

    Args:
        action: 워커 명령 (start, stop, restart, restart-frontend)
        options: command JSON에 포함할 optional payload

    Returns:
        dict: {success: bool, message: str, command_id: str, status: accepted}
    """
    from app.shared.redis.client import RedisClient

    redis_client = await RedisClient.get_client()
    if not redis_client:
        return {
            "success": False,
            "message": "Redis 연결 없음. 워커는 Session 1에서 수동 관리하세요: "
            + _manual_worker_command_hint(action, **options),
        }

    command_id = uuid.uuid4().hex[:12]
    result_key = f"{REDIS_WORKER_RESULTS_KEY}:{command_id}"
    payload = {
        "command_id": command_id,
        "result_key": result_key,
        "action": action,
        "timestamp": datetime.now().isoformat(),
        "source": "api",
    }
    payload.update(options)
    command = json.dumps(payload)

    try:
        await redis_client.delete(result_key)

        # 명령 전송
        await redis_client.lpush(REDIS_WORKER_COMMANDS_KEY, command)
        logger.info(f"[WorkerAPI] Redis 워커 명령 전송: {action}")

        return {
            "success": True,
            "status": "accepted",
            "command_id": command_id,
            "message": f"명령 '{action}'이 접수되었습니다.",
        }

    except Exception as e:
        logger.error(f"[WorkerAPI] Redis 워커 명령 전송 실패: {e}")
        return {"success": False, "message": f"Redis 명령 전송 실패: {str(e)}"}


async def _get_worker_command_result(command_id: str) -> dict:
    from app.shared.redis.client import RedisClient

    redis_client = await RedisClient.get_client()
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis에 연결할 수 없습니다.")

    key = f"{REDIS_WORKER_RESULTS_KEY}:{command_id}"
    raw = await redis_client.lindex(key, 0)
    if raw is None:
        return {
            "success": True,
            "status": "pending",
            "command_id": command_id,
            "message": "명령 처리 대기 중입니다.",
        }
    result_json = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
    return {
        "success": bool(result_json.get("success", False)),
        "status": "completed" if result_json.get("success", False) else "failed",
        "command_id": command_id,
        "message": result_json.get("message", "완료"),
        "pid": result_json.get("pid"),
        "result": result_json,
    }


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
        status_data["uptime_seconds"] = calculate_uptime(status_data.get("started_at"))

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
        pid=result.get("pid"),
        status=result.get("status"),
        command_id=result.get("command_id")
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
        pid=result.get("pid"),
        status=result.get("status"),
        command_id=result.get("command_id")
    )


@router.post("/restart", response_model=WorkerActionResponse)
async def restart_worker():
    """워커 프로세스를 재시작합니다. (Redis → Session 1 리스너)"""
    result = await _send_worker_command("restart")
    return WorkerActionResponse(
        success=result["success"],
        message=result["message"],
        pid=result.get("pid"),
        status=result.get("status"),
        command_id=result.get("command_id")
    )


@router.post("/restart-frontend", response_model=WorkerActionResponse)
async def restart_frontend(public: bool = False):
    """프론트엔드를 재시작합니다. (Redis → Session 1 리스너)"""
    result = await _send_worker_command("restart-frontend", public=bool(public))
    return WorkerActionResponse(
        success=result["success"],
        message=result["message"],
        pid=result.get("pid"),
        status=result.get("status"),
        command_id=result.get("command_id")
    )


@router.get("/commands/{command_id}")
async def get_worker_command_result(command_id: str):
    """워커 명령 결과를 non-blocking으로 조회합니다."""
    return await _get_worker_command_result(command_id)


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

    health = {
        "is_running": False,
        "is_healthy": False,
        "details": {}
    }

    if pid and is_process_running(pid):
        health["is_running"] = True
        health["details"]["pid"] = pid
        health["details"]["memory_mb"] = get_process_memory(pid)

        # Redis TTL 기반 heartbeat 확인
        redis_health = WorkerHealthRedis.check("naver", pid=pid)
        if redis_health and redis_health.get("source") == "redis":
            ttl = redis_health.get("ttl_remaining", 0)
            health["details"]["seconds_since_heartbeat"] = max(0, 30 - ttl)
            health["is_healthy"] = True
        else:
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
            SET global_pause = 1, paused_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
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
            SET global_pause = 0, paused_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """))

        # running/queued 상태인 활성화된 스케줄을 pending으로 리셋하여 워커가 다시 시작하도록 함
        reset_result = db.execute(text("""
            UPDATE monitor_schedules
            SET run_status = 'pending', is_active = false
            WHERE is_enabled = true AND run_status IN ('running', 'queued')
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
    Redis heartbeat 기반으로 판정 — worker_status DB 컬럼 미존재 대응.
    """
    redis_health = WorkerHealthRedis.check("naver")
    last_heartbeat = redis_health["updated_at"] if redis_health else None
    status_data = get_worker_status_from_db()
    pid = status_data.get("pid")
    available = bool(redis_health and pid and is_process_running(pid))
    return BrowserStatusResponse(
        available=available,
        error=status_data.get("error_message"),
        recovery_attempts=0,
        permanently_failed=False,
        last_heartbeat=last_heartbeat
    )
