"""태스크 스케줄 API 라우트."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import TaskSchedule, TaskScheduleRun
from app.services.schedule_contracts import validate_no_exact_time_windows
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
    requires_time_window_repair: bool = False
    candidate_count_next_24h: Optional[int] = None
    schedule_health: Optional[str] = None
    schedule_health_reason: Optional[str] = None
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
    created_count: int = 0  # 신규 추가
    updated_count: int = 0  # 업데이트
    unchanged_count: int = 0  # 중복 (변경없음)
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
    try:
        validate_no_exact_time_windows(data.schedule_value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    schedule = service.create_schedule(
        name=data.name,
        target_type=data.target_type,
        schedule_type=data.schedule_type,
        display_name=data.display_name,
        target_config=data.target_config,
        schedule_value=data.schedule_value,
        enabled=data.enabled
    )
    return _schedule_to_response(schedule, service)


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

    return [_schedule_to_response(s, service) for s in schedules]


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
    return _schedule_to_response(schedule, service)


@router.put("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: int,
    data: UpdateScheduleSchema,
    db: Session = Depends(get_db)
):
    """스케줄 업데이트."""
    service = TaskScheduleService(db)

    updates = data.model_dump(exclude_unset=True)
    if "schedule_value" in updates:
        try:
            validate_no_exact_time_windows(updates["schedule_value"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    schedule = service.update_schedule(schedule_id, **updates)

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _schedule_to_response(schedule, service)


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
        items=[_run_to_response(r, db) for r in result["items"]],
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


class RunPostResponse(BaseModel):
    """실행에서 수집된 포스트 응답 스키마."""
    id: int
    post_id: str
    account: str
    url: str | None
    caption: str | None
    collected_at: datetime
    status: str  # 'created' | 'updated' | 'unchanged'
    has_duplicate_post_id: bool  # 같은 post_id를 가진 포스트가 여러 개 존재

    class Config:
        from_attributes = True


@router.get("/schedules/{schedule_id}/runs/{run_id}/posts")
async def get_run_posts(
    schedule_id: int,
    run_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """실행에서 수집된 포스트 목록 조회."""
    from app.models import InstagramPost
    from sqlalchemy import func

    service = TaskScheduleService(db)

    # 스케줄 및 실행 존재 확인
    schedule = service.get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    run = service.get_run_by_id(run_id)
    if not run or run.schedule_id != schedule_id:
        raise HTTPException(status_code=404, detail="Run not found")

    # Instagram 스케줄만 지원
    if schedule.target_type != "instagram_feed":
        raise HTTPException(
            status_code=400,
            detail="포스트 조회는 Instagram 스케줄만 지원합니다"
        )

    # 해당 run에서 발견된 포스트 조회 (last_seen_run_id 사용)
    offset = (page - 1) * limit
    posts_query = db.query(InstagramPost).filter(
        InstagramPost.last_seen_run_id == run_id
    ).order_by(InstagramPost.last_seen_at.desc())

    total = posts_query.count()
    posts = posts_query.offset(offset).limit(limit).all()

    # 각 포스트에 대해 신규/업데이트/중복 판별
    result_posts = []
    for post in posts:
        # 상태 판별
        if post.crawl_run_id == run_id:
            # 이번 실행에서 처음 생성됨
            status = 'created'
        elif post.updated_at and abs((post.updated_at - run.started_at).total_seconds()) < 60:
            # updated_at이 run 시작 시간과 1분 이내면 이번 실행에서 업데이트됨
            status = 'updated'
        else:
            # 그 외는 중복 (변경 없이 발견만 됨)
            status = 'unchanged'

        # 같은 post_id를 가진 포스트가 2개 이상 있는지 확인
        duplicate_count = db.query(func.count(InstagramPost.id)).filter(
            InstagramPost.post_id == post.post_id
        ).scalar()
        has_duplicate_post_id = duplicate_count > 1

        result_posts.append(RunPostResponse(
            id=post.id,
            post_id=post.post_id,
            account=post.account,
            url=post.url,
            caption=post.caption,
            collected_at=post.collected_at,
            status=status,
            has_duplicate_post_id=has_duplicate_post_id
        ))

    return {
        "items": result_posts,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }


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
        items=[_run_to_response(r, db) for r in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


# ============= Helper Functions =============

def _schedule_to_response(
    schedule: TaskSchedule,
    service: TaskScheduleService | None = None,
) -> ScheduleResponse:
    """스케줄을 응답 스키마로 변환."""
    health = service.get_schedule_health(schedule) if service else {}
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
        requires_time_window_repair=bool(health.get("requires_time_window_repair", False)),
        candidate_count_next_24h=health.get("candidate_count"),
        schedule_health=health.get("health"),
        schedule_health_reason=health.get("reason"),
        created_at=schedule.created_at,
        updated_at=schedule.updated_at
    )


def _run_to_response(run: TaskScheduleRun, db: Session = None) -> ScheduleRunResponse:
    """실행을 응답 스키마로 변환."""
    from app.models import InstagramPost
    from sqlalchemy.orm import joinedload

    created_count = 0
    updated_count = 0
    unchanged_count = 0

    # Instagram 스케줄인 경우에만 집계
    if db:
        # schedule 관계 로드
        if not run.schedule:
            db.refresh(run, ['schedule'])

        if run.schedule and run.schedule.target_type == "instagram_feed":
            # 해당 run에서 발견된 포스트 조회
            posts = db.query(InstagramPost).filter(
                InstagramPost.last_seen_run_id == run.id
            ).all()

            for post in posts:
                if post.crawl_run_id == run.id:
                    created_count += 1
                elif post.updated_at and abs((post.updated_at - run.started_at).total_seconds()) < 60:
                    updated_count += 1
                else:
                    unchanged_count += 1

    return ScheduleRunResponse(
        id=run.id,
        schedule_id=run.schedule_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        collected_count=run.collected_count,
        saved_count=run.saved_count,
        created_count=created_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
        stop_reason=run.stop_reason,
        error_message=run.error_message,
        worker_id=run.worker_id,
        duration_seconds=run.duration_seconds
    )
