"""수집 관리 API 라우트."""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.collect_service import CollectService
from app.services.crawl_schedule_service import CrawlScheduleService
from app.schemas.collect import CollectedPostList, CollectedPostBase, CrawlHistoryList
from app.models import CrawlSchedule, CrawlRequest

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

    CrawlRequest와 CrawlScheduleRun을 통합하여 조회합니다.
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


@router.get("/schedules")
async def get_schedules(
    db: Session = Depends(get_db),
):
    """전체 스케줄 목록 조회."""
    schedules = db.query(CrawlSchedule).order_by(CrawlSchedule.target_type, CrawlSchedule.name).all()
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


@router.post("/schedules/{schedule_id}/toggle")
async def toggle_schedule(
    schedule_id: int,
    enabled: bool = Query(..., description="활성화 여부"),
    db: Session = Depends(get_db),
):
    """스케줄 활성화/비활성화."""
    service = CrawlScheduleService(db)
    schedule = service.toggle_schedule(schedule_id, enabled)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"success": True, "enabled": schedule.enabled}


@router.post("/schedules/{schedule_id}/run")
async def trigger_schedule_run(
    schedule_id: int,
    db: Session = Depends(get_db),
):
    """스케줄 즉시 실행 요청.

    스케줄에 대응하는 크롤링 요청을 즉시 생성합니다.
    """
    schedule = db.query(CrawlSchedule).filter(CrawlSchedule.id == schedule_id).first()
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

    # 범용 크롤링 스케줄의 경우
    else:
        # TODO: 범용 크롤링 스케줄 즉시 실행 구현
        return {
            "success": False,
            "message": "현재 이 스케줄 타입은 즉시 실행을 지원하지 않습니다",
        }
