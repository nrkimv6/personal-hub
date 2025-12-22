"""
스케줄러 관리 API 라우트
Windows 작업 스케줄러 관리
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.services.scheduler_service import scheduler_service
from app.models.scheduled_task_log import ScheduledTaskLog
from app.schemas.scheduler import (
    ScheduledTaskResponse,
    ScheduledTaskListResponse,
    TaskUpdateRequest,
    TaskLogResponse,
    TaskLogListResponse,
)

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


@router.get("/tasks", response_model=ScheduledTaskListResponse)
async def get_scheduled_tasks():
    """등록된 스케줄 작업 목록 조회"""
    try:
        tasks = scheduler_service.get_tasks()
        task_responses = [ScheduledTaskResponse(**task) for task in tasks]
        return ScheduledTaskListResponse(tasks=task_responses, total=len(task_responses))
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"작업 목록 조회 실패: {str(e)}")


@router.get("/tasks/{task_name}", response_model=ScheduledTaskResponse)
async def get_scheduled_task(task_name: str):
    """특정 작업 상세 조회"""
    try:
        task = scheduler_service.get_task(task_name)
        if not task:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
        return ScheduledTaskResponse(**task)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"작업 조회 실패: {str(e)}")


@router.post("/tasks/{task_name}/run")
async def run_task(task_name: str):
    """작업 즉시 실행"""
    try:
        success = scheduler_service.run_task(task_name)
        if not success:
            raise HTTPException(status_code=500, detail="작업 실행 실패")
        return {"status": "started", "task_name": task_name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"작업 실행 실패: {str(e)}")


@router.patch("/tasks/{task_name}")
async def update_task(task_name: str, request: TaskUpdateRequest):
    """작업 활성화/비활성화"""
    try:
        if request.enabled:
            success = scheduler_service.enable_task(task_name)
        else:
            success = scheduler_service.disable_task(task_name)

        if not success:
            raise HTTPException(status_code=500, detail="작업 상태 변경 실패")

        return {"status": "updated", "task_name": task_name, "enabled": request.enabled}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"작업 상태 변경 실패: {str(e)}")


@router.get("/logs", response_model=TaskLogListResponse)
async def get_task_logs(
    task_name: Optional[str] = Query(None, description="작업명으로 필터링"),
    limit: int = Query(50, ge=1, le=200, description="최대 조회 개수"),
    db: Session = Depends(get_db),
):
    """작업 실행 로그 조회"""
    query = db.query(ScheduledTaskLog)

    if task_name:
        # 허용된 작업명만 필터링
        if task_name in scheduler_service.ALLOWED_TASKS:
            query = query.filter(ScheduledTaskLog.task_name == task_name)
        else:
            raise HTTPException(status_code=400, detail=f"허용되지 않은 작업명: {task_name}")

    logs = query.order_by(ScheduledTaskLog.started_at.desc()).limit(limit).all()
    log_responses = [TaskLogResponse.model_validate(log) for log in logs]
    return TaskLogListResponse(logs=log_responses, total=len(log_responses))


@router.get("/logs/{task_name}", response_model=TaskLogListResponse)
async def get_task_logs_by_name(
    task_name: str,
    limit: int = Query(50, ge=1, le=200, description="최대 조회 개수"),
    db: Session = Depends(get_db),
):
    """특정 작업의 실행 로그 조회"""
    # 허용된 작업명만 필터링
    if task_name not in scheduler_service.ALLOWED_TASKS:
        raise HTTPException(status_code=400, detail=f"허용되지 않은 작업명: {task_name}")

    logs = (
        db.query(ScheduledTaskLog)
        .filter(ScheduledTaskLog.task_name == task_name)
        .order_by(ScheduledTaskLog.started_at.desc())
        .limit(limit)
        .all()
    )
    log_responses = [TaskLogResponse.model_validate(log) for log in logs]
    return TaskLogListResponse(logs=log_responses, total=len(log_responses))
