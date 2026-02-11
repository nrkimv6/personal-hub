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
):
    """작업 목록 조회"""
    return db_service.get_tasks(status=status, limit=limit, offset=offset)


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


__all__ = ['router']
