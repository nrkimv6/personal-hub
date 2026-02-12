"""작업 목록 API"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.modules.auto_next.schemas import TaskListResponse, TaskResponse
from app.modules.auto_next.services.db_service import db_service

router = APIRouter()


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
