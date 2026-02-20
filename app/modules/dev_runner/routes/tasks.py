"""작업 목록 API"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.modules.dev_runner.schemas import TaskListResponse, TaskResponse, CurrentTrackingResponse
from app.modules.dev_runner.services.db_service import db_service

try:
    import redis as redis_lib
    _redis_client = redis_lib.Redis(
        host="localhost", port=6379,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
except Exception:
    _redis_client = None

router = APIRouter()

REDIS_STATE_KEY = "plan-runner:state"


@router.get("/tasks/current-tracking", response_model=Optional[CurrentTrackingResponse])
async def get_current_tracking():
    """
    TaskTracker가 현재 추적 중인 체크박스 조회 (Redis 기반, TTL 60초).
    실행 중이 아니거나 정보가 없으면 null 반환.
    """
    if not _redis_client:
        return None

    try:
        text = _redis_client.get(f"{REDIS_STATE_KEY}:current_task_text")
        confidence = _redis_client.get(f"{REDIS_STATE_KEY}:current_task_confidence")

        if not text or not confidence:
            return None

        # str 디코딩
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        if isinstance(confidence, bytes):
            confidence = confidence.decode("utf-8")

        line_num_raw = _redis_client.get(f"{REDIS_STATE_KEY}:current_task_line_num")
        plan_file_raw = _redis_client.get(f"{REDIS_STATE_KEY}:current_task_plan_file")

        line_num = None
        if line_num_raw:
            try:
                line_num = int(line_num_raw.decode("utf-8") if isinstance(line_num_raw, bytes) else line_num_raw)
            except (ValueError, AttributeError):
                pass

        plan_file = None
        if plan_file_raw:
            plan_file = plan_file_raw.decode("utf-8") if isinstance(plan_file_raw, bytes) else plan_file_raw

        return CurrentTrackingResponse(
            text=text,
            confidence=confidence,
            line_num=line_num,
            plan_file=plan_file,
            stale=False,  # TTL 기반 — 키가 살아있으면 stale 아님
        )
    except Exception:
        return None


@router.get("/tasks", response_model=TaskListResponse)
async def get_tasks(
    status: Optional[str] = Query(None, description="작업 상태 필터 (pending/running/success/failed/skipped)"),
    limit: int = Query(50, ge=1, le=200, description="최대 조회 개수"),
    offset: int = Query(0, ge=0, description="오프셋"),
    source_path: Optional[str] = Query(None, description="Plan/TODO 파일 경로로 필터"),
):
    """작업 목록 조회"""
    return db_service.get_tasks(status=status, limit=limit, offset=offset, source_path=source_path)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """특정 작업 조회"""
    task = db_service.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """작업 삭제"""
    success = db_service.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return {"message": "Task deleted successfully", "task_id": task_id}


@router.delete("/tasks")
async def delete_completed_tasks(
    source_path: Optional[str] = Query(None, description="Plan/TODO 파일 경로로 필터 (없으면 전체)")
):
    """완료된 작업 일괄 삭제"""
    deleted = db_service.delete_completed_tasks(source_path=source_path)
    return {"message": f"Deleted {deleted} completed tasks", "deleted": deleted}


@router.delete("/tasks/old")
async def delete_old_tasks(
    hours: int = Query(24, ge=1, le=720, description="완료 후 경과 시간 (1~720시간)"),
    source_path: Optional[str] = Query(None, description="Plan/TODO 파일 경로로 필터"),
):
    """일정 시간 이상 된 완료 작업 삭제"""
    deleted = db_service.delete_old_tasks(hours, source_path=source_path)
    return {
        "message": f"Deleted {deleted} tasks older than {hours} hours",
        "deleted": deleted,
        "hours": hours
    }


__all__ = ['router']
