"""수집 관리 API 라우트."""

import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.collect_service import CollectService
from app.services.task_schedule_service import TaskScheduleService
from app.schemas.collect import CollectedPostList, CollectedPostBase, CrawlHistoryList
from app.models import TaskSchedule, CrawlRequest
from app.models.google_search import GoogleSearchQueue, GoogleSavedSearch

router = APIRouter(prefix="/collect", tags=["collect"])


@router.get("/posts", response_model=CollectedPostList)
async def get_collected_posts(
    source_type: Optional[str] = Query(None, description="소스 타입 (instagram, web)"),
    url_type: Optional[str] = Query(None, description="URL 타입 필터"),
    classification: Optional[str] = Query(None, description="분류 상태 (event, popup, uncategorized, unclassified)"),
    search: Optional[str] = Query(None, description="검색어"),
    date_from: Optional[datetime] = Query(None, description="시작 날짜"),
    date_to: Optional[datetime] = Query(None, description="종료 날짜"),
    is_active: Optional[bool] = Query(None, description="활성 상태 (Instagram 전용)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 개수"),
    db: Session = Depends(get_db),
):
    """통합 게시물 목록 조회.

    Instagram 게시물과 CrawledPages를 통합하여 조회합니다.
    """
    service = CollectService(db)
    posts, total = service.get_posts_paginated(
        page=page,
        limit=limit,
        source_type=source_type,
        url_type=url_type,
        classification=classification,
        search=search,
        date_from=date_from,
        date_to=date_to,
        is_active=is_active,
    )

    total_pages = (total + limit - 1) // limit

    return CollectedPostList(
        items=posts,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.get("/url-types", response_model=List[str])
async def get_url_types(
    db: Session = Depends(get_db),
):
    """사용 가능한 URL 타입 목록 조회."""
    service = CollectService(db)
    return service.get_url_types()


@router.get("/history", response_model=CrawlHistoryList)
async def get_crawl_history(
    source_type: Optional[str] = Query(None, description="소스 타입 (instagram, web)"),
    status: Optional[str] = Query(None, description="상태 (pending, processing, completed, failed)"),
    period: Optional[str] = Query("week", description="기간 (today, week, month, all)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 개수"),
    db: Session = Depends(get_db),
):
    """통합 크롤링 이력 조회.

    CrawlRequest와 TaskScheduleRun을 통합하여 조회합니다.
    """
    service = CollectService(db)
    items, total, stats = service.get_crawl_history(
        page=page,
        limit=limit,
        source_type=source_type,
        status=status,
        period=period if period != "all" else None,
    )

    total_pages = (total + limit - 1) // limit

    return CrawlHistoryList(
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


# ============= Schedule Endpoints =============

class ScheduleResponse(BaseModel):
    """스케줄 응답 스키마."""
    id: int
    name: str
    display_name: Optional[str] = None
    target_type: str
    schedule_type: str
    enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CollectScheduleCreate(BaseModel):
    """스케줄 생성 요청 스키마."""
    target_type: str  # instagram_feed, google_search, writing_task
    target_config: Optional[Dict[str, Any]] = None
    display_name: Optional[str] = None
    schedule_type: str = "time_window"
    schedule_value: Optional[Dict[str, Any]] = None


def _generate_schedule_name(data: CollectScheduleCreate) -> str:
    """스케줄 타입과 설정에 따라 고유한 스케줄 이름 생성."""
    if data.target_type == "instagram_feed":
        account_id = data.target_config.get("service_account_id") if data.target_config else None
        return f"instagram_feed_account_{account_id}"
    elif data.target_type == "google_search":
        saved_id = data.target_config.get("saved_search_id") if data.target_config else None
        return f"google_search_{saved_id}"
    elif data.target_type == "writing_task":
        return "writing_task_default"
    else:
        return f"{data.target_type}_{uuid.uuid4().hex[:8]}"


@router.get("/schedules")
async def get_schedules(
    db: Session = Depends(get_db),
):
    """전체 스케줄 목록 조회."""
    schedules = db.query(TaskSchedule).order_by(TaskSchedule.target_type, TaskSchedule.name).all()
    return [
        ScheduleResponse(
            id=s.id,
            name=s.name,
            display_name=s.display_name,
            target_type=s.target_type,
            schedule_type=s.schedule_type,
            enabled=s.enabled,
            last_run_at=s.last_run_at,
            next_run_at=s.next_run_at,
        )
        for s in schedules
    ]


@router.post("/schedules", response_model=ScheduleResponse)
async def create_schedule(
    data: CollectScheduleCreate,
    db: Session = Depends(get_db),
):
    """통합 스케줄 생성 API.

    지원 타입:
    - instagram_feed: Instagram 피드 수집 (target_config.service_account_id 필요)
    - google_search: Google 검색 수집 (target_config.saved_search_id 필요)
    - writing_task: 글쓰기 태스크
    """
    schedule_service = TaskScheduleService(db)

    # 타입별 검증 및 중복 체크
    if data.target_type == "instagram_feed":
        if not data.target_config or not data.target_config.get("service_account_id"):
            raise HTTPException(
                status_code=400,
                detail="Instagram 스케줄에는 service_account_id가 필요합니다"
            )
        account_id = data.target_config["service_account_id"]
        schedule_name = f"instagram_feed_account_{account_id}"
        existing = schedule_service.get_schedule_by_name(schedule_name)
        if existing:
            raise HTTPException(
                status_code=400,
                detail="이미 해당 계정의 스케줄이 존재합니다"
            )
        # display_name 자동 생성
        if not data.display_name:
            data.display_name = f"Instagram 피드 (계정 {account_id})"

    elif data.target_type == "google_search":
        if not data.target_config or not data.target_config.get("saved_search_id"):
            raise HTTPException(
                status_code=400,
                detail="Google 검색 스케줄에는 saved_search_id가 필요합니다"
            )
        saved_id = data.target_config["saved_search_id"]
        # 저장된 검색 존재 확인
        saved_search = db.query(GoogleSavedSearch).filter_by(id=saved_id).first()
        if not saved_search:
            raise HTTPException(
                status_code=404,
                detail="저장된 검색을 찾을 수 없습니다"
            )
        schedule_name = f"google_search_{saved_id}"
        existing = schedule_service.get_schedule_by_name(schedule_name)
        if existing:
            raise HTTPException(
                status_code=400,
                detail="이미 해당 검색의 스케줄이 존재합니다"
            )
        # display_name 자동 생성
        if not data.display_name:
            data.display_name = f"Google 검색 ({saved_search.name})"

    elif data.target_type == "writing_task":
        schedule_name = "writing_task_default"
        existing = schedule_service.get_schedule_by_name(schedule_name)
        if existing:
            raise HTTPException(
                status_code=400,
                detail="이미 글쓰기 스케줄이 존재합니다"
            )
        if not data.display_name:
            data.display_name = "글쓰기 태스크"

    else:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 스케줄 타입입니다: {data.target_type}"
        )

    # 스케줄 생성
    schedule = schedule_service.create_schedule(
        name=schedule_name,
        display_name=data.display_name,
        target_type=data.target_type,
        target_config=data.target_config,
        schedule_type=data.schedule_type,
        schedule_value=json.dumps(data.schedule_value) if data.schedule_value else None,
        enabled=True
    )

    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        display_name=schedule.display_name,
        target_type=schedule.target_type,
        schedule_type=schedule.schedule_type,
        enabled=schedule.enabled,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
    )


@router.post("/schedules/{schedule_id}/toggle")
async def toggle_schedule(
    schedule_id: int,
    enabled: bool = Query(..., description="활성화 여부"),
    db: Session = Depends(get_db),
):
    """스케줄 활성화/비활성화."""
    service = TaskScheduleService(db)
    schedule = service.toggle_schedule(schedule_id, enabled)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"success": True, "enabled": schedule.enabled}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    delete_runs: bool = Query(False, description="실행 이력도 함께 삭제"),
    db: Session = Depends(get_db),
):
    """스케줄 삭제.

    Args:
        schedule_id: 삭제할 스케줄 ID
        delete_runs: True면 실행 이력도 함께 삭제 (기본: False - 이력 유지)
    """
    service = TaskScheduleService(db)

    # 스케줄 존재 확인
    schedule = service.get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # 실행 이력 수 확인 (삭제 전 정보 제공)
    run_count = service.get_run_count(schedule_id)

    # 이력이 있는데 delete_runs=False인 경우 경고
    if run_count > 0 and not delete_runs:
        raise HTTPException(
            status_code=400,
            detail=f"스케줄에 {run_count}개의 실행 이력이 있습니다. "
                   "이력도 삭제하려면 delete_runs=true를 사용하세요."
        )

    success = service.delete_schedule(schedule_id, delete_runs=delete_runs)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete schedule")

    return {
        "success": True,
        "message": f"스케줄이 삭제되었습니다" + (f" (이력 {run_count}개 포함)" if delete_runs and run_count > 0 else ""),
        "deleted_runs": run_count if delete_runs else 0,
    }


@router.post("/schedules/{schedule_id}/run")
async def trigger_schedule_run(
    schedule_id: int,
    db: Session = Depends(get_db),
):
    """스케줄 즉시 실행 요청.

    스케줄에 대응하는 크롤링 요청을 즉시 생성합니다.
    """
    schedule = db.query(TaskSchedule).filter(TaskSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # 이미 대기 중인 요청이 있는지 확인
    existing = db.query(CrawlRequest).filter(
        CrawlRequest.status.in_(['pending', 'processing']),
        CrawlRequest.url_type.like(f'{schedule.target_type}%')
    ).first()

    if existing:
        return {
            "success": False,
            "message": "이미 대기 중인 요청이 있습니다",
            "request_id": existing.id,
        }

    # Instagram 피드 스케줄의 경우
    if schedule.target_type == 'instagram_feed':
        target_config = schedule.get_target_config() if schedule.target_config else {}
        service_account_id = target_config.get('service_account_id')

        if not service_account_id:
            raise HTTPException(
                status_code=400,
                detail="스케줄에 계정이 설정되지 않았습니다"
            )

        # CrawlRequest (범용 테이블)에 요청 생성
        request = CrawlRequest(
            url=f"instagram://feed?account_id={service_account_id}",
            url_type="instagram_feed",
            status="pending",
            requested_by="manual",
        )
        db.add(request)
        db.commit()
        db.refresh(request)

        return {
            "success": True,
            "message": f"크롤링 요청 #{request.id}이(가) 생성되었습니다",
            "request_id": request.id,
        }

    # Google 검색 스케줄의 경우
    elif schedule.target_type == 'google_search':
        target_config = schedule.get_target_config() if schedule.target_config else {}
        saved_search_id = target_config.get('saved_search_id')

        if not saved_search_id:
            raise HTTPException(
                status_code=400,
                detail="저장된 검색이 설정되지 않았습니다"
            )

        saved_search = db.query(GoogleSavedSearch).filter_by(id=saved_search_id).first()
        if not saved_search:
            raise HTTPException(
                status_code=404,
                detail="저장된 검색을 찾을 수 없습니다"
            )

        # GoogleSearchQueue에 추가
        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved_search.query,
            date_filter=saved_search.date_filter,
            max_pages=saved_search.max_pages,
            saved_search_id=saved_search_id,
            status="pending"
        )
        db.add(queue_item)
        db.commit()

        return {
            "success": True,
            "message": "검색이 요청되었습니다",
            "search_id": queue_item.search_id,
        }

    # 글쓰기 태스크 스케줄의 경우
    elif schedule.target_type == 'writing_task':
        # 스케줄 실행 기록 생성
        schedule_service = TaskScheduleService(db)
        run = schedule_service.start_run(
            schedule_id=schedule.id,
            worker_id="manual",
            config_snapshot={"source": "manual"}
        )

        return {
            "success": True,
            "message": "글쓰기 태스크가 예약되었습니다",
            "run_id": run.id,
        }

    # 지원하지 않는 스케줄 타입
    else:
        return {
            "success": False,
            "message": f"스케줄 타입 '{schedule.target_type}'은(는) 즉시 실행을 지원하지 않습니다",
        }
