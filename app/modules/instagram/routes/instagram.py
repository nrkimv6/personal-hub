"""Instagram API Routes."""

import logging
from datetime import date
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.browser_service import get_browser_service
from app.services.account_service import account_service
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
    CrawlRequestSchema,
)
from ..services import PostService, CrawlService, CrawlRequestService

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

@router.post("/crawl/manual", response_model=CrawlRequestSchema)
async def request_manual_crawl(
    account_id: int = Query(..., description="수집 계정 ID"),
    db: Session = Depends(get_db),
):
    """수동 크롤링 요청.

    요청은 큐에 추가되며 워커가 처리합니다.
    이미 대기 중인 요청이 있으면 기존 요청을 반환합니다.
    """
    request_service = CrawlRequestService(db)

    # 이미 활성 요청이 있는지 확인
    if request_service.has_active_request(account_id):
        existing = request_service.get_pending_request(account_id)
        if existing:
            return CrawlRequestSchema.model_validate(existing)

    # 새 요청 생성
    request = request_service.create_request(account_id, requested_by="manual")
    return CrawlRequestSchema.model_validate(request)


@router.get("/crawl/requests", response_model=List[CrawlRequestSchema])
async def get_crawl_requests(
    limit: int = Query(10, ge=1, le=50, description="조회 개수"),
    account_id: Optional[int] = Query(None, description="계정 필터"),
    db: Session = Depends(get_db),
):
    """크롤링 요청 목록 조회."""
    request_service = CrawlRequestService(db)
    requests = request_service.get_recent_requests(limit=limit, account_id=account_id)
    return [CrawlRequestSchema.model_validate(r) for r in requests]


@router.get("/crawl/requests/pending", response_model=List[CrawlRequestSchema])
async def get_pending_requests(
    limit: int = Query(10, ge=1, le=50, description="조회 개수"),
    db: Session = Depends(get_db),
):
    """대기 중인 크롤링 요청 목록."""
    request_service = CrawlRequestService(db)
    requests = request_service.get_pending_requests(limit=limit)
    return [CrawlRequestSchema.model_validate(r) for r in requests]


@router.post("/crawl", response_model=CrawlResponse)
async def run_crawl(
    account_id: int = Query(..., description="수집 계정 ID"),
    options: Optional[CrawlOptionsSchema] = None,
    db: Session = Depends(get_db),
):
    """수동 크롤링 실행 (레거시 - /crawl/manual 사용 권장).

    Note: 실제 크롤링은 워커에서 실행됩니다.
    이 API는 크롤링 요청을 큐에 추가합니다.
    """
    request_service = CrawlRequestService(db)
    request = request_service.create_request(account_id, requested_by="manual")

    return CrawlResponse(
        success=True,
        total_collected=0,
        new_saved=0,
        crawl_run_id=None,
        message=f"Crawl request #{request.id} queued. Worker will execute soon.",
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
            retry_count=getattr(run, 'retry_count', 0) or 0,
            retry_of_run_id=getattr(run, 'retry_of_run_id', None),
            failure_reason=getattr(run, 'failure_reason', None),
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

    return _config_to_schema(config)


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
        min_interval_hours=update.min_interval_hours,
        duplicate_stop_count=update.duplicate_stop_count,
        max_retries=update.max_retries,
        retry_interval_minutes=update.retry_interval_minutes,
        account_id=update.account_id,
    )

    return _config_to_schema(config)


@router.get("/schedule/today", response_model=List[TodayScheduleItem])
async def get_today_schedule(
    db: Session = Depends(get_db),
):
    """오늘 스케줄 조회."""
    service = CrawlService(db)
    return service.get_today_schedule()


# ============== Login ==============

@router.post("/login/open-browser")
async def open_login_browser(
    account_id: int = Query(..., description="계정 ID"),
    db: Session = Depends(get_db),
):
    """Instagram 수동 로그인용 브라우저 열기.

    지정된 계정의 브라우저 프로필로 Instagram 로그인 페이지를 엽니다.
    사용자가 수동으로 로그인하면 세션이 저장됩니다.
    """
    account = account_service.get_by_id(db, account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    browser_service = get_browser_service()
    result = await browser_service.open_browser_for_account(
        account_id, "https://www.instagram.com/"
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("message", "브라우저 열기 실패"))

    return {
        "success": True,
        "message": "Instagram 로그인 페이지가 열렸습니다. 수동으로 로그인해주세요.",
        "account_id": account_id,
        "account_name": account.name,
    }


# ============== Helpers ==============

def _config_to_schema(config) -> ScheduleConfigSchema:
    """InstagramScheduleConfig 모델을 ScheduleConfigSchema로 변환."""
    return ScheduleConfigSchema(
        id=config.id,
        enabled=config.enabled,
        daily_runs=config.daily_runs,
        time_windows=[TimeWindow(**tw) for tw in (config.time_windows or [])],
        max_posts=config.max_posts,
        scroll_count=config.scroll_count,
        min_interval_hours=getattr(config, 'min_interval_hours', 2) or 2,
        duplicate_stop_count=getattr(config, 'duplicate_stop_count', 5) or 5,
        max_retries=getattr(config, 'max_retries', 3) or 3,
        retry_interval_minutes=getattr(config, 'retry_interval_minutes', 5) or 5,
        account_id=getattr(config, 'account_id', None),
        account_name=config.account.name if getattr(config, 'account', None) else None,
        updated_at=config.updated_at,
    )


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
