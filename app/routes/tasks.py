"""태스크 스케줄 API 라우트."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import TaskSchedule, TaskScheduleRun
from app.services.task_schedule_service import TaskScheduleService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# ============= Schedule Schemas =============

class CreateScheduleSchema(BaseModel):
    """스케줄 생성 스키마."""
    name: str
    target_type: str
    schedule_type: str
    display_name: Optional[str] = None
    target_config: Optional[dict] = None
    schedule_value: Optional[str] = None
    enabled: bool = True


class UpdateScheduleSchema(BaseModel):
    """스케줄 업데이트 스키마."""
    display_name: Optional[str] = None
    target_config: Optional[dict] = None
    schedule_value: Optional[str] = None
    enabled: Optional[bool] = None


class ScheduleResponse(BaseModel):
    """스케줄 응답 스키마."""
    id: int
    name: str
    display_name: Optional[str] = None
    target_type: str
    target_config: Optional[dict] = None
    schedule_type: str
    schedule_value: Optional[str] = None
    enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ScheduleRunResponse(BaseModel):
    """스케줄 실행 응답 스키마."""
    id: int
    schedule_id: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str
    collected_count: int = 0
    saved_count: int = 0
    stop_reason: Optional[str] = None
    error_message: Optional[str] = None
    worker_id: Optional[str] = None
    duration_seconds: Optional[int] = None

    class Config:
        from_attributes = True


class PaginatedRunsResponse(BaseModel):
    """페이징된 실행 목록 응답."""
    items: list[ScheduleRunResponse]
    total: int
    page: int
    limit: int
    pages: int


class RunStatsResponse(BaseModel):
    """실행 통계 응답."""
    period_days: int
    total_runs: int
    completed_runs: int
    failed_runs: int
    success_rate: float
    total_collected: int
    total_saved: int


# ============= Schedule Endpoints =============

@router.post("/schedules", response_model=ScheduleResponse)
async def create_schedule(
    data: CreateScheduleSchema,
    db: Session = Depends(get_db)
):
    """스케줄 생성."""
    service = TaskScheduleService(db)

    # 중복 이름 체크
    existing = service.get_schedule_by_name(data.name)
    if existing:
        raise HTTPException(status_code=400, detail="Schedule name already exists")

    schedule = service.create_schedule(
        name=data.name,
        target_type=data.target_type,
        schedule_type=data.schedule_type,
        display_name=data.display_name,
        target_config=data.target_config,
        schedule_value=data.schedule_value,
        enabled=data.enabled
    )
    return _schedule_to_response(schedule)


@router.get("/schedules")
async def get_schedules(
    target_type: Optional[str] = None,
    enabled_only: bool = True,
    db: Session = Depends(get_db)
):
    """스케줄 목록 조회."""
    service = TaskScheduleService(db)

    if target_type:
        schedules = service.get_schedules_by_type(target_type, enabled_only)
    else:
        query = db.query(TaskSchedule)
        if enabled_only:
            query = query.filter(TaskSchedule.enabled == True)
        schedules = query.all()

    return [_schedule_to_response(s) for s in schedules]


@router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: int,
    db: Session = Depends(get_db)
):
    """스케줄 상세 조회."""
    service = TaskScheduleService(db)
    schedule = service.get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _schedule_to_response(schedule)


@router.put("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: int,
    data: UpdateScheduleSchema,
    db: Session = Depends(get_db)
):
    """스케줄 업데이트."""
    service = TaskScheduleService(db)

    updates = data.model_dump(exclude_unset=True)
    schedule = service.update_schedule(schedule_id, **updates)

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _schedule_to_response(schedule)


@router.post("/schedules/{schedule_id}/toggle")
async def toggle_schedule(
    schedule_id: int,
    enabled: bool = Query(...),
    db: Session = Depends(get_db)
):
    """스케줄 활성화/비활성화."""
    service = TaskScheduleService(db)
    schedule = service.toggle_schedule(schedule_id, enabled)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"success": True, "enabled": schedule.enabled}


# ============= Schedule Run Endpoints =============

@router.get("/schedules/{schedule_id}/runs", response_model=PaginatedRunsResponse)
async def get_schedule_runs(
    schedule_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """스케줄 실행 이력 조회."""
    service = TaskScheduleService(db)

    # 스케줄 존재 확인
    schedule = service.get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    result = service.get_runs_paginated(
        schedule_id=schedule_id,
        page=page,
        limit=limit,
        status=status
    )
    return PaginatedRunsResponse(
        items=[_run_to_response(r) for r in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


@router.get("/schedules/{schedule_id}/stats", response_model=RunStatsResponse)
async def get_schedule_stats(
    schedule_id: int,
    days: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """스케줄 실행 통계 조회."""
    service = TaskScheduleService(db)

    # 스케줄 존재 확인
    schedule = service.get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    stats = service.get_run_stats(schedule_id=schedule_id, days=days)
    return stats


@router.get("/runs", response_model=PaginatedRunsResponse)
async def get_all_runs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """전체 실행 이력 조회."""
    service = TaskScheduleService(db)
    result = service.get_runs_paginated(
        page=page,
        limit=limit,
        status=status
    )
    return PaginatedRunsResponse(
        items=[_run_to_response(r) for r in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


# ============= Helper Functions =============

def _schedule_to_response(schedule: TaskSchedule) -> ScheduleResponse:
    """스케줄을 응답 스키마로 변환."""
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        display_name=schedule.display_name,
        target_type=schedule.target_type,
        target_config=schedule.get_target_config(),
        schedule_type=schedule.schedule_type,
        schedule_value=schedule.schedule_value,
        enabled=schedule.enabled,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at
    )


def _run_to_response(run: TaskScheduleRun) -> ScheduleRunResponse:
    """실행을 응답 스키마로 변환."""
    return ScheduleRunResponse(
        id=run.id,
        schedule_id=run.schedule_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        collected_count=run.collected_count,
        saved_count=run.saved_count,
        stop_reason=run.stop_reason,
        error_message=run.error_message,
        worker_id=run.worker_id,
        duration_seconds=run.duration_seconds
    )
