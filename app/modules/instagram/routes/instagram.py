"""Instagram API Routes."""

import logging
from datetime import date
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from ..models.schemas import (
    PostSchema,
    PostListResponse,
    CrawlOptionsSchema,
    CrawlResponse,
    CrawlRunSchema,
    ScheduleConfigSchema,
    ScheduleConfigUpdateSchema,
    StatsSchema,
    TodayScheduleItem,
    TimeWindow,
)
from ..services import PostService, CrawlService

logger = logging.getLogger("instagram.api")

router = APIRouter(prefix="/api/v1/instagram", tags=["instagram"])


# ============== Posts ==============

@router.get("/posts", response_model=PostListResponse)
async def get_posts(
    account: Optional[str] = Query(None, description="계정명 필터"),
    date_from: Optional[date] = Query(None, description="시작 날짜"),
    date_to: Optional[date] = Query(None, description="종료 날짜"),
    is_ad: Optional[bool] = Query(None, description="광고 필터"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 개수"),
    db: Session = Depends(get_db),
):
    """수집된 게시물 목록 조회."""
    service = PostService(db)
    offset = (page - 1) * limit

    posts, total = service.get_posts(
        account=account,
        date_from=date_from,
        date_to=date_to,
        is_ad=is_ad,
        limit=limit,
        offset=offset,
    )

    return PostListResponse(
        posts=[_post_to_schema(p) for p in posts],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/posts/{post_id}", response_model=PostSchema)
async def get_post(
    post_id: int,
    db: Session = Depends(get_db),
):
    """게시물 상세 조회."""
    service = PostService(db)
    post = service.get_post_by_id(post_id)

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    return _post_to_schema(post)


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
):
    """게시물 삭제."""
    service = PostService(db)

    if not service.delete_post(post_id):
        raise HTTPException(status_code=404, detail="Post not found")

    return {"message": "Post deleted successfully"}


# ============== Crawl ==============

@router.post("/crawl", response_model=CrawlResponse)
async def run_crawl(
    account_id: int = Query(..., description="수집 계정 ID"),
    options: Optional[CrawlOptionsSchema] = None,
    db: Session = Depends(get_db),
):
    """수동 크롤링 실행.

    Note: 실제 크롤링은 워커에서 실행됩니다.
    이 API는 크롤링 요청을 큐에 추가합니다.
    """
    # TODO: 실제 구현에서는 워커에 크롤링 요청을 전달
    # 현재는 바로 실행하지 않고 응답만 반환

    return CrawlResponse(
        success=False,
        total_collected=0,
        new_saved=0,
        message="Crawl request queued. Worker will execute soon.",
    )


@router.get("/runs", response_model=List[CrawlRunSchema])
async def get_crawl_runs(
    limit: int = Query(10, ge=1, le=50, description="조회 개수"),
    account_id: Optional[int] = Query(None, description="계정 필터"),
    db: Session = Depends(get_db),
):
    """크롤링 실행 기록 조회."""
    service = CrawlService(db)
    runs = service.get_crawl_runs(limit=limit, account_id=account_id)

    return [
        CrawlRunSchema(
            id=run.id,
            account_id=run.account_id,
            started_at=run.started_at,
            finished_at=run.finished_at,
            success=run.success,
            total_collected=run.total_collected,
            new_saved=run.new_saved,
            error_message=run.error_message,
        )
        for run in runs
    ]


# ============== Stats ==============

@router.get("/stats", response_model=StatsSchema)
async def get_stats(
    db: Session = Depends(get_db),
):
    """통계 조회."""
    service = CrawlService(db)
    return service.get_stats()


# ============== Schedule ==============

@router.get("/schedule", response_model=ScheduleConfigSchema)
async def get_schedule_config(
    db: Session = Depends(get_db),
):
    """스케줄 설정 조회."""
    service = CrawlService(db)
    config = service.get_schedule_config()

    if not config:
        # 기본 설정 생성
        config = service.update_schedule_config()

    return ScheduleConfigSchema(
        id=config.id,
        enabled=config.enabled,
        daily_runs=config.daily_runs,
        time_windows=[TimeWindow(**tw) for tw in (config.time_windows or [])],
        max_posts=config.max_posts,
        scroll_count=config.scroll_count,
        updated_at=config.updated_at,
    )


@router.put("/schedule", response_model=ScheduleConfigSchema)
async def update_schedule_config(
    update: ScheduleConfigUpdateSchema,
    db: Session = Depends(get_db),
):
    """스케줄 설정 업데이트."""
    service = CrawlService(db)

    config = service.update_schedule_config(
        enabled=update.enabled,
        daily_runs=update.daily_runs,
        time_windows=update.time_windows,
        max_posts=update.max_posts,
        scroll_count=update.scroll_count,
    )

    return ScheduleConfigSchema(
        id=config.id,
        enabled=config.enabled,
        daily_runs=config.daily_runs,
        time_windows=[TimeWindow(**tw) for tw in (config.time_windows or [])],
        max_posts=config.max_posts,
        scroll_count=config.scroll_count,
        updated_at=config.updated_at,
    )


@router.get("/schedule/today", response_model=List[TodayScheduleItem])
async def get_today_schedule(
    db: Session = Depends(get_db),
):
    """오늘 스케줄 조회."""
    service = CrawlService(db)
    return service.get_today_schedule()


# ============== Helpers ==============

def _post_to_schema(post) -> PostSchema:
    """InstagramPost 모델을 PostSchema로 변환."""
    from ..models.schemas import ImageInfo

    images = []
    if post.images:
        for img in post.images:
            if isinstance(img, dict):
                images.append(ImageInfo(src=img.get("src", ""), alt=img.get("alt")))

    return PostSchema(
        id=post.id,
        post_id=post.post_id,
        account=post.account,
        url=post.url,
        caption=post.caption,
        images=images,
        posted_at=post.posted_at,
        display_time=post.display_time,
        is_ad=post.is_ad,
        collected_at=post.collected_at,
        crawl_run_id=post.crawl_run_id,
    )
