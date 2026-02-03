"""Google 검색 스케줄 API 라우트."""

import json
import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.models.google_search import GoogleSavedSearch, GoogleSearchQueue, GoogleSearchHistory, GoogleSearchResult
from app.services.task_schedule_service import TaskScheduleService
from app.modules.google_search.models.schedule_schemas import (
    GoogleSearchScheduleCreate,
    GoogleSearchScheduleUpdate,
    GoogleSearchScheduleResponse,
    ScheduleRunResponse,
    ScheduleRunListResponse,
    ScheduleSearchResultItem,
    ScheduleSearchHistoryItem,
    ScheduleSearchResultsResponse,
    ScheduleRecentResultItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/google/schedule", tags=["google-search-schedule"])


def _schedule_to_response(
    schedule: TaskSchedule,
    saved_search: Optional[GoogleSavedSearch] = None
) -> GoogleSearchScheduleResponse:
    """TaskSchedule을 응답 스키마로 변환."""
    config = schedule.get_target_config()
    schedule_value = json.loads(schedule.schedule_value) if schedule.schedule_value else {}

    return GoogleSearchScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        display_name=schedule.display_name,
        target_type=schedule.target_type,
        target_config=config,
        schedule_type=schedule.schedule_type,
        schedule_value=schedule_value,
        enabled=schedule.enabled,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
        saved_search_name=saved_search.name if saved_search else None,
        saved_search_query=saved_search.query if saved_search else None,
    )


def _run_to_response(run: TaskScheduleRun, search_id: Optional[str] = None) -> ScheduleRunResponse:
    """TaskScheduleRun을 응답 스키마로 변환."""
    return ScheduleRunResponse(
        id=run.id,
        schedule_id=run.schedule_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        collected_count=run.collected_count or 0,
        saved_count=run.saved_count or 0,
        stop_reason=run.stop_reason,
        error_message=run.error_message,
        duration_seconds=run.duration_seconds,
        search_id=search_id,
    )


@router.post("/", response_model=GoogleSearchScheduleResponse, status_code=201)
async def create_google_search_schedule(
    data: GoogleSearchScheduleCreate,
    db: Session = Depends(get_db)
):
    """Google 검색 스케줄 생성."""
    # 저장된 검색 확인
    saved_search = db.query(GoogleSavedSearch).filter_by(id=data.saved_search_id).first()
    if not saved_search:
        raise HTTPException(status_code=404, detail="저장된 검색을 찾을 수 없습니다")

    # 이미 해당 saved_search_id로 스케줄이 있는지 확인
    existing = db.query(TaskSchedule).filter(
        TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH,
        TaskSchedule.target_config.contains(f'"saved_search_id": {data.saved_search_id}')
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="이미 해당 저장된 검색에 대한 스케줄이 존재합니다")

    schedule_service = TaskScheduleService(db)

    # 스케줄 생성
    schedule = schedule_service.create_schedule(
        name=f"google_search_{data.saved_search_id}",
        display_name=data.display_name or f"{saved_search.name} 자동 검색",
        target_type=TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH,
        schedule_type=data.schedule_type,
        target_config={"saved_search_id": data.saved_search_id},
        schedule_value=data.schedule_value.model_dump_json(),
        enabled=data.enabled,
    )

    logger.info(f"Google 검색 스케줄 생성: schedule_id={schedule.id}, saved_search_id={data.saved_search_id}")

    return _schedule_to_response(schedule, saved_search)


@router.get("/", response_model=List[GoogleSearchScheduleResponse])
async def list_google_search_schedules(
    saved_search_id: Optional[int] = Query(None, description="특정 저장된 검색 ID 필터"),
    enabled_only: bool = Query(False, description="활성화된 것만 조회"),
    db: Session = Depends(get_db)
):
    """Google 검색 스케줄 목록 조회."""
    query = db.query(TaskSchedule).filter(
        TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH
    )

    if enabled_only:
        query = query.filter(TaskSchedule.enabled == True)

    schedules = query.order_by(TaskSchedule.created_at.desc()).all()

    result = []
    for schedule in schedules:
        config = schedule.get_target_config()
        schedule_saved_search_id = config.get("saved_search_id")

        # saved_search_id 필터
        if saved_search_id and schedule_saved_search_id != saved_search_id:
            continue

        saved_search = None
        if schedule_saved_search_id:
            saved_search = db.query(GoogleSavedSearch).filter_by(id=schedule_saved_search_id).first()

        result.append(_schedule_to_response(schedule, saved_search))

    return result


@router.get("/recent-results", response_model=List[ScheduleRecentResultItem])
async def get_recent_schedule_results(
    db: Session = Depends(get_db)
):
    """전체 Google 검색 스케줄의 최근 검색 결과 요약.

    각 스케줄별로 마지막 검색 결과를 포함하여 반환합니다.
    """
    schedules = (
        db.query(TaskSchedule)
        .filter(TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH)
        .order_by(TaskSchedule.last_run_at.desc().nullslast())
        .all()
    )

    result = []
    for schedule in schedules:
        config = schedule.get_target_config()
        saved_search_id = config.get("saved_search_id")

        saved_search = None
        if saved_search_id:
            saved_search = db.query(GoogleSavedSearch).filter_by(id=saved_search_id).first()

        # 가장 최근 완료된 검색 큐 항목
        queue_filter = [GoogleSearchQueue.status == "completed"]
        if saved_search_id:
            queue_filter.append(
                (GoogleSearchQueue.schedule_id == schedule.id) |
                (GoogleSearchQueue.saved_search_id == saved_search_id)
            )
        else:
            queue_filter.append(GoogleSearchQueue.schedule_id == schedule.id)

        latest_queue = (
            db.query(GoogleSearchQueue)
            .filter(*queue_filter)
            .order_by(GoogleSearchQueue.completed_at.desc())
            .first()
        )

        last_search = None
        if latest_queue:
            history = db.query(GoogleSearchHistory).filter_by(search_id=latest_queue.search_id).first()
            if history:
                db_results = (
                    db.query(GoogleSearchResult)
                    .filter_by(search_id=latest_queue.search_id)
                    .order_by(GoogleSearchResult.rank)
                    .all()
                )
                last_search = ScheduleSearchHistoryItem(
                    search_id=latest_queue.search_id,
                    query=history.query,
                    date_filter=history.date_filter,
                    status=history.status,
                    total_results=history.total_results,
                    created_at=history.created_at,
                    completed_at=history.completed_at,
                    results=[
                        ScheduleSearchResultItem(
                            rank=r.rank,
                            title=r.title,
                            url=r.url,
                            display_url=r.display_url,
                            snippet=r.snippet,
                            publish_date=r.publish_date,
                        )
                        for r in db_results
                    ],
                )

        result.append(ScheduleRecentResultItem(
            schedule_id=schedule.id,
            schedule_name=schedule.display_name or schedule.name,
            saved_search_name=saved_search.name if saved_search else None,
            query=saved_search.query if saved_search else None,
            enabled=schedule.enabled,
            last_search=last_search,
            last_run_at=schedule.last_run_at,
        ))

    return result


@router.get("/{schedule_id}", response_model=GoogleSearchScheduleResponse)
async def get_google_search_schedule(
    schedule_id: int,
    db: Session = Depends(get_db)
):
    """Google 검색 스케줄 조회."""
    schedule = db.query(TaskSchedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    if schedule.target_type != TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH:
        raise HTTPException(status_code=400, detail="Google 검색 스케줄이 아닙니다")

    config = schedule.get_target_config()
    saved_search = None
    if config.get("saved_search_id"):
        saved_search = db.query(GoogleSavedSearch).filter_by(id=config["saved_search_id"]).first()

    return _schedule_to_response(schedule, saved_search)


@router.put("/{schedule_id}", response_model=GoogleSearchScheduleResponse)
async def update_google_search_schedule(
    schedule_id: int,
    data: GoogleSearchScheduleUpdate,
    db: Session = Depends(get_db)
):
    """Google 검색 스케줄 수정."""
    schedule = db.query(TaskSchedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    if schedule.target_type != TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH:
        raise HTTPException(status_code=400, detail="Google 검색 스케줄이 아닙니다")

    schedule_service = TaskScheduleService(db)

    updates = {}
    if data.display_name is not None:
        updates["display_name"] = data.display_name
    if data.enabled is not None:
        updates["enabled"] = data.enabled
    if data.schedule_value is not None:
        updates["schedule_value"] = data.schedule_value.model_dump_json()

    schedule = schedule_service.update_schedule(schedule_id, **updates)

    config = schedule.get_target_config()
    saved_search = None
    if config.get("saved_search_id"):
        saved_search = db.query(GoogleSavedSearch).filter_by(id=config["saved_search_id"]).first()

    logger.info(f"Google 검색 스케줄 수정: schedule_id={schedule_id}")

    return _schedule_to_response(schedule, saved_search)


@router.delete("/{schedule_id}")
async def delete_google_search_schedule(
    schedule_id: int,
    db: Session = Depends(get_db)
):
    """Google 검색 스케줄 삭제."""
    schedule = db.query(TaskSchedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    if schedule.target_type != TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH:
        raise HTTPException(status_code=400, detail="Google 검색 스케줄이 아닙니다")

    db.delete(schedule)
    db.commit()

    logger.info(f"Google 검색 스케줄 삭제: schedule_id={schedule_id}")

    return {"message": "삭제되었습니다"}


@router.post("/{schedule_id}/enable", response_model=GoogleSearchScheduleResponse)
async def enable_google_search_schedule(
    schedule_id: int,
    db: Session = Depends(get_db)
):
    """Google 검색 스케줄 활성화."""
    schedule_service = TaskScheduleService(db)
    schedule = schedule_service.toggle_schedule(schedule_id, enabled=True)

    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    config = schedule.get_target_config()
    saved_search = None
    if config.get("saved_search_id"):
        saved_search = db.query(GoogleSavedSearch).filter_by(id=config["saved_search_id"]).first()

    return _schedule_to_response(schedule, saved_search)


@router.post("/{schedule_id}/disable", response_model=GoogleSearchScheduleResponse)
async def disable_google_search_schedule(
    schedule_id: int,
    db: Session = Depends(get_db)
):
    """Google 검색 스케줄 비활성화."""
    schedule_service = TaskScheduleService(db)
    schedule = schedule_service.toggle_schedule(schedule_id, enabled=False)

    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    config = schedule.get_target_config()
    saved_search = None
    if config.get("saved_search_id"):
        saved_search = db.query(GoogleSavedSearch).filter_by(id=config["saved_search_id"]).first()

    return _schedule_to_response(schedule, saved_search)


@router.get("/{schedule_id}/runs", response_model=ScheduleRunListResponse)
async def get_schedule_runs(
    schedule_id: int,
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지 크기"),
    status: Optional[str] = Query(None, description="상태 필터 (running, completed, failed)"),
    db: Session = Depends(get_db)
):
    """스케줄 실행 이력 조회."""
    # 스케줄 존재 확인
    schedule = db.query(TaskSchedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    schedule_service = TaskScheduleService(db)
    result = schedule_service.get_runs_paginated(
        schedule_id=schedule_id,
        page=page,
        limit=limit,
        status=status,
    )

    return ScheduleRunListResponse(
        items=[_run_to_response(run) for run in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"],
    )


@router.get("/{schedule_id}/stats")
async def get_schedule_stats(
    schedule_id: int,
    days: int = Query(7, ge=1, le=90, description="통계 기간 (일)"),
    db: Session = Depends(get_db)
):
    """스케줄 실행 통계 조회."""
    # 스케줄 존재 확인
    schedule = db.query(TaskSchedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    schedule_service = TaskScheduleService(db)
    stats = schedule_service.get_run_stats(schedule_id=schedule_id, days=days)

    return stats


@router.get("/{schedule_id}/search-results", response_model=ScheduleSearchResultsResponse)
async def get_schedule_search_results(
    schedule_id: int,
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(10, ge=1, le=50, description="페이지 크기"),
    include_results: bool = Query(True, description="검색 결과 포함 여부"),
    db: Session = Depends(get_db)
):
    """특정 스케줄의 검색 결과 히스토리 조회.

    스케줄에 연결된 저장된 검색의 모든 검색 히스토리와 결과를 반환합니다.
    """
    schedule = db.query(TaskSchedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    if schedule.target_type != TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH:
        raise HTTPException(status_code=400, detail="Google 검색 스케줄이 아닙니다")

    config = schedule.get_target_config()
    saved_search_id = config.get("saved_search_id")

    saved_search = None
    if saved_search_id:
        saved_search = db.query(GoogleSavedSearch).filter_by(id=saved_search_id).first()

    # GoogleSearchQueue에서 이 스케줄/저장된 검색과 연결된 검색 히스토리 조회
    queue_query = db.query(GoogleSearchQueue).filter(
        GoogleSearchQueue.status == "completed"
    )

    # schedule_id가 설정된 항목 우선, 없으면 saved_search_id로 조회
    if saved_search_id:
        queue_query = queue_query.filter(
            (GoogleSearchQueue.schedule_id == schedule_id) |
            (GoogleSearchQueue.saved_search_id == saved_search_id)
        )
    else:
        queue_query = queue_query.filter(GoogleSearchQueue.schedule_id == schedule_id)

    total = queue_query.count()
    queue_items = (
        queue_query
        .order_by(GoogleSearchQueue.completed_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    items = []
    for qi in queue_items:
        history = db.query(GoogleSearchHistory).filter_by(search_id=qi.search_id).first()
        if not history:
            continue

        results = []
        if include_results:
            db_results = (
                db.query(GoogleSearchResult)
                .filter_by(search_id=qi.search_id)
                .order_by(GoogleSearchResult.rank)
                .all()
            )
            results = [
                ScheduleSearchResultItem(
                    rank=r.rank,
                    title=r.title,
                    url=r.url,
                    display_url=r.display_url,
                    snippet=r.snippet,
                    publish_date=r.publish_date,
                )
                for r in db_results
            ]

        items.append(ScheduleSearchHistoryItem(
            search_id=qi.search_id,
            query=history.query,
            date_filter=history.date_filter,
            status=history.status,
            total_results=history.total_results,
            created_at=history.created_at,
            completed_at=history.completed_at,
            results=results,
        ))

    return ScheduleSearchResultsResponse(
        schedule_id=schedule_id,
        schedule_name=schedule.display_name or schedule.name,
        saved_search_name=saved_search.name if saved_search else None,
        query=saved_search.query if saved_search else None,
        items=items,
        total=total,
        page=page,
        limit=limit,
    )


