"""수집 관리 API 라우트."""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.collect_service import CollectService
from app.schemas.collect import CollectedPostList, CollectedPostBase, CrawlHistoryList

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
