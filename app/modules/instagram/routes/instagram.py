"""Instagram API Routes."""

import json
import logging
from datetime import date
from typing import Optional, List
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.shared.service_account import service_account_service
from app.core.config import settings
from ..models.schemas import (
    PostSchema,
    PostListResponse,
    PostUpdateSchema,
    CrawlOptionsSchema,
    CrawlResponse,
    CrawlRunSchema,
    ScheduleConfigSchema,
    ScheduleConfigUpdateSchema,
    StatsSchema,
    TodayScheduleItem,
    TimeWindow,
    CrawlRequestSchema,
    UrlCrawlRequestSchema,
    UrlParseRequestSchema,
    UrlParseResponseSchema,
    GenericUrlCrawlRequestSchema,
    RunListResponse,
    RunStatsSchema,
    DailyTrendItem,
    CrawlEventSchema,
    CrawlRunSummarySchema,
    CrawlHistoryItem,
    CrawlHistoryResponse,
    CrawlRunSummary,
    BatchPostIdsRequest,
)
from ..services.url_parser import (
    parse_instagram_url,
    get_url_type_description,
    InstagramUrlType,
)
from ..services import PostService, CrawlService, CrawlRequestService
from ..services.llm_classifier_service import LLMClassifierService
from app.schemas.service_account import ServiceAccountWithProfile

logger = logging.getLogger("instagram.api")

router = APIRouter(prefix="/api/v1/instagram", tags=["instagram"])


# ============== Accounts ==============

@router.get("/accounts", response_model=List[ServiceAccountWithProfile])
async def get_instagram_accounts(
    db: Session = Depends(get_db),
):
    """Instagram 크롤링에 사용 가능한 서비스 계정 목록 조회."""
    accounts = service_account_service.get_active_accounts_by_type(db, "instagram")
    result = []
    for acc in accounts:
        result.append({
            "id": acc.id,
            "profile_id": acc.profile_id,
            "service_type": acc.service_type,
            "identifier": acc.identifier,
            "is_logged_in": acc.is_logged_in,
            "credentials": acc.credentials,
            "created_at": acc.created_at,
            "updated_at": acc.updated_at,
            "profile_name": acc.profile.name if acc.profile else None,
            "profile_dir": acc.profile.profile_dir if acc.profile else None,
        })
    return result


# ============== Posts ==============

@router.get("/posts", response_model=PostListResponse)
async def get_posts(
    account: Optional[str] = Query(None, description="계정명 필터"),
    date_from: Optional[date] = Query(None, description="시작 날짜"),
    date_to: Optional[date] = Query(None, description="종료 날짜"),
    is_ad: Optional[bool] = Query(None, description="광고 필터 (레거시)"),
    post_type: Optional[str] = Query(None, description="게시물 유형 필터 (NORMAL/SPONSORED/SUGGESTED)"),
    tags: Optional[str] = Query(None, description="태그 필터 (쉼표 구분)"),
    sort_by: Optional[str] = Query(None, description="정렬 기준 (collected_at)"),
    sort_order: Optional[str] = Query("asc", description="정렬 순서 (asc/desc)"),
    is_active: Optional[bool] = Query(None, description="활성화 상태 필터 (true/false/null)"),
    search: Optional[str] = Query(None, description="캡션 검색어"),
    llm_status: Optional[str] = Query(None, description="LLM 분석 상태 필터 (none/pending/processing/completed/failed)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 개수"),
    db: Session = Depends(get_db),
):
    """수집된 게시물 목록 조회."""
    from app.modules.claude_worker.models.llm_request import LLMRequest
    from sqlalchemy import func

    service = PostService(db)
    offset = (page - 1) * limit

    # 태그 파라미터 파싱
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

    # LLM 상태 필터를 위한 post_id 목록 계산
    include_post_ids = None
    exclude_post_ids = None

    if llm_status:
        if llm_status == "none":
            # LLMRequest가 없는 게시물만 조회
            llm_post_ids = (
                db.query(LLMRequest.caller_id)
                .filter(LLMRequest.caller_type == "instagram")
                .distinct()
                .all()
            )
            exclude_post_ids = [int(row[0]) for row in llm_post_ids if row[0] and row[0].isdigit()]
        else:
            # 해당 상태의 최신 LLMRequest가 있는 게시물만 조회
            subquery = (
                db.query(
                    LLMRequest.caller_id,
                    func.max(LLMRequest.requested_at).label("max_requested_at")
                )
                .filter(LLMRequest.caller_type == "instagram")
                .group_by(LLMRequest.caller_id)
                .subquery()
            )

            # 프론트엔드에서 보내는 값 매핑 (classified -> completed)
            status_mapping = {
                "pending": ["pending"],
                "processing": ["processing"],
                "classified": ["completed"],
                "completed": ["completed"],
                "error": ["failed"],
                "failed": ["failed"],
            }
            target_statuses = status_mapping.get(llm_status, [llm_status])

            latest_requests = (
                db.query(LLMRequest.caller_id)
                .join(
                    subquery,
                    (LLMRequest.caller_id == subquery.c.caller_id) &
                    (LLMRequest.requested_at == subquery.c.max_requested_at)
                )
                .filter(
                    LLMRequest.caller_type == "instagram",
                    LLMRequest.status.in_(target_statuses)
                )
                .all()
            )
            include_post_ids = [int(row[0]) for row in latest_requests if row[0] and row[0].isdigit()]

    posts, total = service.get_posts(
        account=account,
        date_from=date_from,
        date_to=date_to,
        is_ad=is_ad,
        post_type=post_type,
        tags=tag_list,
        sort_by=sort_by,
        sort_order=sort_order,
        is_active=is_active,
        search=search,
        include_post_ids=include_post_ids,
        exclude_post_ids=exclude_post_ids,
        limit=limit,
        offset=offset,
    )

    # LLM 상태 조회 (LLMRequest 테이블에서 가져옴)
    post_ids = [p.id for p in posts]
    llm_status_map = {}
    if post_ids:
        # 각 게시물의 최신 LLM 요청 상태 조회
        from sqlalchemy import func
        subquery = (
            db.query(
                LLMRequest.caller_id,
                func.max(LLMRequest.requested_at).label("max_requested_at")
            )
            .filter(
                LLMRequest.caller_type == "instagram",
                LLMRequest.caller_id.in_([str(pid) for pid in post_ids])
            )
            .group_by(LLMRequest.caller_id)
            .subquery()
        )

        latest_requests = (
            db.query(LLMRequest)
            .join(
                subquery,
                (LLMRequest.caller_id == subquery.c.caller_id) &
                (LLMRequest.requested_at == subquery.c.max_requested_at)
            )
            .filter(LLMRequest.caller_type == "instagram")
            .all()
        )

        for req in latest_requests:
            try:
                pid = int(req.caller_id)
                llm_status_map[pid] = req.status
            except (ValueError, TypeError):
                pass

    return PostListResponse(
        posts=[_post_to_schema(p, llm_status_map.get(p.id)) for p in posts],
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

    llm_status = _get_llm_status_for_post(db, post_id)
    return _post_to_schema(post, llm_status)


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


@router.patch("/posts/{post_id}/active", response_model=PostSchema)
async def toggle_post_active(
    post_id: int,
    is_active: bool = Query(..., description="활성화 상태"),
    db: Session = Depends(get_db),
):
    """게시물 활성화/비활성화 토글."""
    service = PostService(db)

    post = service.update_post_active_status(post_id, is_active)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    llm_status = _get_llm_status_for_post(db, post_id)
    return _post_to_schema(post, llm_status)


@router.put("/posts/{post_id}", response_model=PostSchema)
async def update_post(
    post_id: int,
    update: PostUpdateSchema,
    db: Session = Depends(get_db),
):
    """게시물 수정 (태그 변경)."""
    service = PostService(db)

    # 게시물 존재 확인
    post = service.get_post_by_id(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # 태그 업데이트
    if update.tag_ids is not None:
        post = service.update_post_tags(post_id, update.tag_ids)

    llm_status = _get_llm_status_for_post(db, post_id)
    return _post_to_schema(post, llm_status)


@router.post("/posts/batch/delete")
async def batch_delete_posts(
    request: BatchPostIdsRequest,
    db: Session = Depends(get_db),
):
    """게시물 일괄 삭제."""
    service = PostService(db)
    deleted = service.batch_delete(request.post_ids)

    return {
        "success": True,
        "deleted": deleted,
        "total": len(request.post_ids),
    }


@router.post("/posts/batch/deactivate")
async def batch_deactivate_posts(
    request: BatchPostIdsRequest,
    db: Session = Depends(get_db),
):
    """게시물 일괄 비활성화."""
    service = PostService(db)
    updated = service.batch_update_active(request.post_ids, is_active=False)

    return {
        "success": True,
        "updated": updated,
        "total": len(request.post_ids),
    }


@router.post("/posts/batch/analyze")
async def batch_request_llm_analysis(
    request: BatchPostIdsRequest,
    db: Session = Depends(get_db),
):
    """게시물 일괄 AI 분석 요청.

    여러 게시물에 대해 LLM 분류 요청을 생성합니다.
    """
    post_service = PostService(db)
    llm_service = LLMClassifierService(db)

    created_count = 0
    request_ids = []

    for post_id in request.post_ids:
        post = post_service.get_post_by_id(post_id)
        if post:
            llm_request = llm_service.create_request(
                post_id=post_id,
                trigger_tag="manual",
                requested_by="manual",
            )
            created_count += 1
            request_ids.append(llm_request.id)

    return {
        "success": True,
        "created_count": created_count,
        "request_ids": request_ids,
        "total": len(request.post_ids),
    }


@router.post("/posts/{post_id}/analyze")
async def request_llm_analysis(
    post_id: int,
    db: Session = Depends(get_db),
):
    """게시물 AI 분석 요청.

    지정된 게시물에 대해 LLM 분류 요청을 생성합니다.
    분류 결과는 Event/Popup/Uncategorized 테이블에 저장됩니다.
    """
    post_service = PostService(db)
    llm_service = LLMClassifierService(db)

    # 게시물 존재 확인
    post = post_service.get_post_by_id(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # LLM 분류 요청 생성
    request = llm_service.create_request(
        post_id=post_id,
        trigger_tag="manual",
        requested_by="manual",
    )

    return {
        "success": True,
        "request_id": request.id,
        "post_id": post_id,
        "message": "LLM 분류 요청이 생성되었습니다.",
    }


@router.post("/posts/{post_id}/recrawl", response_model=CrawlRequestSchema)
async def recrawl_post(
    post_id: int,
    db: Session = Depends(get_db),
):
    """개별 게시물 재크롤링 요청.

    지정된 게시물의 URL로 다시 크롤링하여 최신 정보를 수집합니다.
    요청은 큐에 추가되며 워커가 처리합니다.
    """
    post_service = PostService(db)
    request_service = CrawlRequestService(db)

    # 게시물 존재 확인
    post = post_service.get_post_by_id(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if not post.url:
        raise HTTPException(status_code=400, detail="Post has no URL to recrawl")

    # 게시물의 service_account_id 확인
    service_account_id = post.service_account_id
    if not service_account_id:
        raise HTTPException(status_code=400, detail="Post has no associated account")

    # 재크롤링 요청 생성
    request = request_service.create_single_post_request(
        post_id=post_id,
        service_account_id=service_account_id,
        requested_by="manual",
    )

    return CrawlRequestSchema.model_validate(request)


# ============== URL Parsing ==============

@router.post("/url/parse", response_model=UrlParseResponseSchema)
async def parse_url(body: UrlParseRequestSchema):
    """Instagram URL 파싱.

    URL을 분석하여 타입과 관련 정보를 반환합니다.

    지원되는 URL 타입:
    - main_feed: 메인 피드 (https://www.instagram.com/)
    - account_profile: 계정 프로필 (https://www.instagram.com/{username}/)
    - account_reels: 계정 릴스 (https://www.instagram.com/{username}/reels/)
    - single_post: 개별 게시물 (https://www.instagram.com/p/{id}/)
    - single_reel: 개별 릴스 (https://www.instagram.com/reel/{id}/)
    - reels_explore: 릴스 탐색 (https://www.instagram.com/reels/)
    - hashtag: 해시태그 (https://www.instagram.com/explore/tags/{tag}/)
    - story: 스토리 (지원 불가)
    """
    parsed = parse_instagram_url(body.url)

    return UrlParseResponseSchema(
        url_type=parsed.url_type.value,
        url_type_description=get_url_type_description(parsed.url_type),
        is_supported=parsed.is_supported,
        username=parsed.username,
        post_id=parsed.post_id,
        reel_id=parsed.reel_id,
        hashtag=parsed.hashtag,
        original_url=parsed.original_url,
    )


@router.post("/posts/crawl-url", response_model=CrawlRequestSchema)
async def crawl_post_by_url(
    body: UrlCrawlRequestSchema,
    db: Session = Depends(get_db),
):
    """URL로 단일 게시물 수집 요청.

    Instagram 게시물 URL을 입력받아 해당 게시물을 수집합니다.
    - 새 게시물이면 DB에 추가
    - 기존 게시물이면 정보 업데이트
    """
    import re

    request_service = CrawlRequestService(db)

    # URL 형식 검증
    url = body.url.strip()
    if not re.match(r'^https?://(www\.)?instagram\.com/p/[A-Za-z0-9_-]+/?', url):
        raise HTTPException(status_code=400, detail="Invalid Instagram post URL. Must be in format: https://www.instagram.com/p/...")

    # 계정 존재 확인
    account = service_account_service.get_by_id(db, body.service_account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {body.service_account_id} not found")

    # URL 크롤링 요청 생성
    request = request_service.create_url_crawl_request(
        url=url,
        service_account_id=body.service_account_id,
        requested_by="manual",
    )

    return CrawlRequestSchema.model_validate(request)


@router.post("/crawl/url", response_model=CrawlRequestSchema)
async def crawl_by_generic_url(
    body: GenericUrlCrawlRequestSchema,
    db: Session = Depends(get_db),
):
    """범용 URL 기반 크롤링 요청.

    다양한 Instagram URL 타입을 지원합니다:
    - 계정 프로필: https://www.instagram.com/{username}/
    - 계정 릴스: https://www.instagram.com/{username}/reels/
    - 개별 게시물: https://www.instagram.com/p/{id}/
    - 개별 릴스: https://www.instagram.com/reel/{id}/
    - 릴스 탐색: https://www.instagram.com/reels/
    - 해시태그: https://www.instagram.com/explore/tags/{tag}/

    스토리는 지원되지 않습니다.
    """
    request_service = CrawlRequestService(db)

    # URL 파싱
    parsed = parse_instagram_url(body.url)

    if not parsed.is_supported:
        if parsed.url_type == InstagramUrlType.STORY:
            raise HTTPException(
                status_code=400,
                detail="스토리 크롤링은 지원되지 않습니다. Instagram 정책상 스토리는 24시간 후 삭제되며 API 접근이 불가합니다."
            )
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 URL 형식입니다: {body.url}"
        )

    # 계정 존재 확인
    account = service_account_service.get_by_id(db, body.service_account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {body.service_account_id} not found")

    # 크롤링 요청 생성
    request = request_service.create_generic_url_crawl_request(
        url=body.url,
        url_type=parsed.url_type.value,
        service_account_id=body.service_account_id,
        max_posts=body.max_posts,
        scroll_count=body.scroll_count,
        requested_by="manual",
    )

    return CrawlRequestSchema.model_validate(request)


# ============== Crawl ==============

@router.post("/crawl/manual", response_model=CrawlRequestSchema)
async def request_manual_crawl(
    service_account_id: int = Query(..., description="수집 계정 ID"),
    db: Session = Depends(get_db),
):
    """수동 크롤링 요청.

    요청은 큐에 추가되며 워커가 처리합니다.
    이미 대기 중인 요청이 있으면 기존 요청을 반환합니다.
    """
    request_service = CrawlRequestService(db)

    # 이미 활성 요청이 있는지 확인
    if request_service.has_active_request(service_account_id):
        existing = request_service.get_pending_request(service_account_id)
        if existing:
            return CrawlRequestSchema.model_validate(existing)

    # 새 요청 생성
    request = request_service.create_request(service_account_id, requested_by="manual")
    return CrawlRequestSchema.model_validate(request)


@router.get("/crawl/requests", response_model=List[CrawlRequestSchema])
async def get_crawl_requests(
    limit: int = Query(10, ge=1, le=50, description="조회 개수"),
    service_account_id: Optional[int] = Query(None, description="계정 필터"),
    db: Session = Depends(get_db),
):
    """크롤링 요청 목록 조회."""
    request_service = CrawlRequestService(db)
    requests = request_service.get_recent_requests(limit=limit, service_account_id=service_account_id)
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


@router.post("/crawl/history/{request_id}/retry", response_model=CrawlRequestSchema)
async def retry_crawl_request(
    request_id: int,
    db: Session = Depends(get_db),
):
    """크롤링 요청 재시도.

    실패한 크롤링 요청을 다시 시도합니다.
    원본 요청의 타입에 따라 적절한 새 요청을 생성합니다.
    """
    request_service = CrawlRequestService(db)

    # 원본 요청 조회
    original = request_service.get_request_by_id(request_id)
    if not original:
        raise HTTPException(status_code=404, detail="Request not found")

    # 재시도 요청 생성
    if original.request_type == "feed":
        # 피드 크롤링 재시도
        new_request = request_service.create_request(
            service_account_id=original.service_account_id,
            requested_by="retry",
        )
    elif original.request_type == "single_post":
        # 개별 게시물 재크롤링 재시도
        if not original.target_post_id:
            raise HTTPException(status_code=400, detail="Original request has no target post")
        new_request = request_service.create_single_post_request(
            post_id=original.target_post_id,
            service_account_id=original.service_account_id,
            requested_by="retry",
        )
    elif original.request_type == "single_post_url":
        # URL 크롤링 재시도
        if not original.target_url:
            raise HTTPException(status_code=400, detail="Original request has no target URL")
        new_request = request_service.create_url_crawl_request(
            url=original.target_url,
            service_account_id=original.service_account_id,
            requested_by="retry",
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown request type: {original.request_type}")

    return CrawlRequestSchema.model_validate(new_request)


@router.get("/crawl/history", response_model=CrawlHistoryResponse)
async def get_crawl_history(
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 개수"),
    request_type: Optional[str] = Query(None, description="요청 타입 (feed, single_post, single_post_url)"),
    requested_by: Optional[str] = Query(None, description="요청 출처 (manual, scheduler, retry)"),
    status: Optional[str] = Query(None, description="상태 (pending, processing, completed, failed)"),
    period: Optional[str] = Query(None, description="기간 (today, week, month)"),
    service_account_id: Optional[int] = Query(None, description="계정 필터"),
    db: Session = Depends(get_db),
):
    """크롤링 이력 통합 조회.

    모든 크롤링 활동(피드 크롤링, URL 요청, 개별 게시물 재크롤링)을 한눈에 조회.
    """
    from app.models import CrawlScheduleRun

    request_service = CrawlRequestService(db)
    requests, total = request_service.get_requests_paginated(
        page=page,
        limit=limit,
        request_type=request_type,
        requested_by=requested_by,
        status=status,
        period=period,
        service_account_id=service_account_id,
    )

    items = []
    for req in requests:
        # CrawlScheduleRun 정보 조회 (있는 경우)
        crawl_run_summary = None
        if req.result_id and req.result_type == "crawl_schedule_run":
            run = db.query(CrawlScheduleRun).filter(CrawlScheduleRun.id == req.result_id).first()
            if run:
                duration = run.duration_seconds
                crawl_run_summary = CrawlRunSummary(
                    id=run.id,
                    total_collected=run.collected_count or 0,
                    new_saved=run.saved_count or 0,
                    duration_seconds=duration,
                    stop_reason=run.stop_reason,
                )

        # URL에서 service_account_id 추출 (instagram://feed?account_id=X 형식)
        service_account_id_from_url = None
        if req.url and "account_id=" in req.url:
            try:
                service_account_id_from_url = int(req.url.split("account_id=")[1].split("&")[0])
            except (ValueError, IndexError):
                pass

        # url_type에서 request_type 매핑
        request_type_map = {
            "instagram_feed": "feed",
            "instagram_post": "single_post",
            "instagram_account": "account_feed",
            "instagram_hashtag": "hashtag",
            "instagram_reels": "reels",
        }
        request_type = request_type_map.get(req.url_type, req.url_type)

        # target_url은 URL 자체 (instagram:// 스킴 제외)
        target_url = req.url if not req.url.startswith("instagram://") else None

        # target_post_id 추출 (instagram://post/123 형식)
        target_post_id = None
        if req.url and req.url.startswith("instagram://post/"):
            try:
                target_post_id = int(req.url.split("/")[3].split("?")[0])
            except (ValueError, IndexError):
                pass

        items.append(CrawlHistoryItem(
            id=req.id,
            service_account_id=service_account_id_from_url,
            requested_at=req.requested_at,
            requested_by=req.requested_by,
            request_type=request_type,
            target_url=target_url,
            target_post_id=target_post_id,
            status=req.status,
            processed_at=req.processed_at,
            crawl_run_id=req.result_id if req.result_type == "crawl_schedule_run" else None,
            error_message=req.error_message,
            crawl_run=crawl_run_summary,
        ))

    return CrawlHistoryResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )


@router.post("/crawl", response_model=CrawlResponse)
async def run_crawl(
    service_account_id: int = Query(..., description="수집 계정 ID"),
    options: Optional[CrawlOptionsSchema] = None,
    db: Session = Depends(get_db),
):
    """수동 크롤링 실행 (레거시 - /crawl/manual 사용 권장).

    Note: 실제 크롤링은 워커에서 실행됩니다.
    이 API는 크롤링 요청을 큐에 추가합니다.
    """
    request_service = CrawlRequestService(db)
    request = request_service.create_request(service_account_id, requested_by="manual")

    return CrawlResponse(
        success=True,
        total_collected=0,
        new_saved=0,
        crawl_run_id=None,
        message=f"Crawl request #{request.id} queued. Worker will execute soon.",
    )


@router.get("/runs", response_model=RunListResponse)
async def get_crawl_runs(
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 개수"),
    period: Optional[str] = Query(None, description="기간 필터 (1d, 7d, 30d, all)"),
    status: Optional[str] = Query(None, description="상태 필터 (success, failed, all)"),
    service_account_id: Optional[int] = Query(None, description="계정 필터"),
    db: Session = Depends(get_db),
):
    """크롤링 실행 기록 조회 (페이징 지원)."""
    service = CrawlService(db)
    runs, total = service.get_crawl_runs_paginated(
        page=page,
        limit=limit,
        period=period,
        status=status,
        service_account_id=service_account_id,
    )

    return RunListResponse(
        runs=[_run_to_schema(run) for run in runs],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/runs/stats", response_model=RunStatsSchema)
async def get_run_stats(
    days: int = Query(7, ge=1, le=30, description="통계 기간 (일)"),
    db: Session = Depends(get_db),
):
    """실행 통계 조회."""
    service = CrawlService(db)
    stats = service.get_run_stats(days=days)

    return RunStatsSchema(
        total_runs=stats["total_runs"],
        success_runs=stats["success_runs"],
        failed_runs=stats["failed_runs"],
        success_rate=stats["success_rate"],
        avg_collected=stats["avg_collected"],
        avg_duration_seconds=stats["avg_duration_seconds"],
        daily_trend=[DailyTrendItem(**item) for item in stats["daily_trend"]],
    )


@router.get("/runs/{run_id}", response_model=CrawlRunSchema)
async def get_crawl_run(
    run_id: int,
    db: Session = Depends(get_db),
):
    """크롤링 실행 기록 상세 조회."""
    service = CrawlService(db)
    run = service.get_crawl_run_by_id(run_id)

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return _run_to_schema(run)


@router.get("/runs/{run_id}/posts", response_model=PostListResponse)
async def get_run_posts(
    run_id: int,
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 개수"),
    db: Session = Depends(get_db),
):
    """특정 실행에서 수집된 게시물 조회."""
    service = PostService(db)
    offset = (page - 1) * limit

    posts, total = service.get_posts_by_run_id(run_id, limit=limit, offset=offset)

    return PostListResponse(
        posts=[_post_to_schema(p) for p in posts],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/runs/{run_id}/events", response_model=List[CrawlEventSchema])
async def get_crawl_run_events(
    run_id: int,
    event_type: Optional[str] = Query(None, description="이벤트 타입 필터"),
    limit: int = Query(100, ge=1, le=500, description="최대 개수"),
    db: Session = Depends(get_db),
):
    """크롤링 실행의 이벤트 로그 조회."""
    service = CrawlService(db)
    run = service.get_crawl_run_by_id(run_id)

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    events = service.get_crawl_events(run_id, event_type=event_type, limit=limit)
    return events


@router.get("/runs/{run_id}/summary", response_model=CrawlRunSummarySchema)
async def get_crawl_run_summary(
    run_id: int,
    db: Session = Depends(get_db),
):
    """크롤링 실행 요약 정보 조회."""
    service = CrawlService(db)
    run = service.get_crawl_run_by_id(run_id)

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    events = service.get_crawl_events(run_id, limit=500)

    # 이벤트 타입별 개수 집계
    event_counts = {}
    for event in events:
        event_type = event.event_type
        event_counts[event_type] = event_counts.get(event_type, 0) + 1

    return CrawlRunSummarySchema(
        run=_run_to_schema(run),
        events=[CrawlEventSchema.model_validate(e) for e in events],
        event_counts=event_counts,
    )


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
        service_account_id=update.service_account_id,
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

def _create_browser_command(
    db: Session,
    command_type: str,
    service_account_id: int,
    request_data: Optional[dict] = None
) -> int:
    """브라우저 명령 생성 (워커에서 처리)"""
    request_json = json.dumps(request_data) if request_data else None

    db.execute(text("""
        INSERT INTO browser_commands (command_type, service_account_id, status, request_data)
        VALUES (:command_type, :service_account_id, 'pending', :request_data)
    """), {
        "command_type": command_type,
        "service_account_id": service_account_id,
        "request_data": request_json
    })
    db.commit()

    last_id = db.execute(text("SELECT last_insert_rowid()")).scalar()
    return last_id


@router.post("/login/open-browser")
async def open_login_browser(
    service_account_id: int = Query(..., description="계정 ID"),
    db: Session = Depends(get_db),
):
    """Instagram 수동 로그인용 브라우저 열기.

    지정된 계정의 브라우저 프로필로 Instagram 로그인 페이지를 엽니다.
    사용자가 수동으로 로그인하면 세션이 저장됩니다.
    """
    account = service_account_service.get_by_id(db, service_account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {service_account_id} not found")

    # browser_commands 테이블을 통해 워커에 명령 전달
    command_id = _create_browser_command(
        db,
        command_type="instagram_login",
        service_account_id=service_account_id,
        request_data={"url": "https://www.instagram.com/"}
    )

    return {
        "success": True,
        "message": "Instagram 로그인 페이지 열기 명령이 생성되었습니다. 잠시 후 브라우저가 열립니다.",
        "command_id": command_id,
        "service_account_id": service_account_id,
        "account_name": account.profile.name if account.profile else account.identifier,
    }


@router.post("/login/check")
async def check_login_status(
    service_account_id: int = Query(..., description="계정 ID"),
    db: Session = Depends(get_db),
):
    """Instagram 로그인 상태 확인.

    지정된 계정으로 Instagram에 접속하여 로그인 상태를 확인하고 DB를 업데이트합니다.
    """
    account = service_account_service.get_by_id(db, service_account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {service_account_id} not found")

    command_id = _create_browser_command(
        db,
        command_type="instagram_check_login",
        service_account_id=service_account_id,
        request_data={}
    )

    return {
        "success": True,
        "message": "Instagram 로그인 상태 체크 명령이 생성되었습니다.",
        "command_id": command_id,
        "service_account_id": service_account_id,
    }


# ============== Image Proxy ==============

ALLOWED_IMAGE_HOSTS = [
    "scontent.cdninstagram.com",
    "instagram.com",
]


@router.get("/proxy-image")
async def proxy_image(
    url: str = Query(..., description="이미지 URL"),
):
    """Instagram CDN 이미지 프록시.

    CORS 문제를 우회하여 Instagram 이미지를 가져옵니다.
    html2canvas 캡쳐 시 사용됩니다.
    """
    # URL 검증 (Instagram CDN만 허용)
    parsed = urlparse(url)
    if not any(host in parsed.netloc for host in ALLOWED_IMAGE_HOSTS):
        # scontent-xxx-x.cdninstagram.com 형태도 허용
        if not (parsed.netloc.startswith("scontent") and "cdninstagram.com" in parsed.netloc):
            raise HTTPException(status_code=400, detail="허용되지 않은 이미지 호스트입니다")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://www.instagram.com/",
                },
                follow_redirects=True,
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "image/jpeg")

            return Response(
                content=response.content,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "Access-Control-Allow-Origin": "*",
                },
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="이미지 요청 시간 초과")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="이미지를 가져올 수 없습니다")
    except Exception as e:
        logger.error(f"Image proxy error: {e}")
        raise HTTPException(status_code=500, detail="이미지 프록시 오류")


# ============== Helpers ==============

def _run_to_schema(run) -> CrawlRunSchema:
    """CrawlScheduleRun 모델을 CrawlRunSchema로 변환."""
    import json

    # schedule의 target_config에서 service_account_id 추출
    service_account_id = None
    if run.schedule:
        target_config = run.schedule.get_target_config()
        service_account_id = target_config.get("service_account_id")

    return CrawlRunSchema(
        id=run.id,
        service_account_id=service_account_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        success=(run.status == "completed"),
        total_collected=run.collected_count or 0,
        new_saved=run.saved_count or 0,
        error_message=run.error_message,
        retry_count=run.retry_count or 0,
        retry_of_run_id=run.retry_of_run_id,
        failure_reason=run.stop_reason if run.status == "failed" else None,
    )


def _config_to_schema(config) -> ScheduleConfigSchema:
    """CrawlSchedule 모델을 ScheduleConfigSchema로 변환."""
    import json

    # target_config에서 설정 추출
    target_config = config.get_target_config()

    # schedule_value에서 설정 추출
    schedule_value = {}
    if config.schedule_value:
        try:
            schedule_value = json.loads(config.schedule_value)
        except json.JSONDecodeError:
            pass

    # service_account 정보 조회를 위해 DB 조회가 필요하지만,
    # 여기서는 target_config의 값만 사용
    service_account_id = target_config.get("service_account_id")

    return ScheduleConfigSchema(
        id=config.id,
        enabled=config.enabled,
        daily_runs=schedule_value.get("daily_runs", 3),
        time_windows=[TimeWindow(**tw) for tw in schedule_value.get("time_windows", [])],
        max_posts=target_config.get("max_posts", 20),
        scroll_count=target_config.get("scroll_count", 3),
        min_interval_hours=target_config.get("min_interval_hours", 2),
        duplicate_stop_count=target_config.get("duplicate_stop_count", 5),
        max_retries=target_config.get("max_retries", 3),
        retry_interval_minutes=target_config.get("retry_interval_minutes", 5),
        service_account_id=service_account_id,
        account_name=None,  # DB 조회 없이는 알 수 없음
        updated_at=config.updated_at,
    )


def _get_llm_status_for_post(db: Session, post_id: int) -> Optional[str]:
    """단일 게시물의 LLM 분석 상태 조회."""
    from app.modules.claude_worker.models.llm_request import LLMRequest

    request = (
        db.query(LLMRequest)
        .filter(
            LLMRequest.caller_type == "instagram",
            LLMRequest.caller_id == str(post_id),
        )
        .order_by(LLMRequest.requested_at.desc())
        .first()
    )

    return request.status if request else None


def _post_to_schema(post, llm_status: Optional[str] = None) -> PostSchema:
    """InstagramPost 모델을 PostSchema로 변환.

    Args:
        post: InstagramPost 모델 객체
        llm_status: LLM 분석 상태 (외부에서 조회하여 전달)
    """
    from ..models.schemas import ImageInfo, TagInfoSchema

    images = []
    if post.images:
        for img in post.images:
            if isinstance(img, dict):
                images.append(ImageInfo(src=img.get("src", ""), alt=img.get("alt")))

    # 태그 정보 추출
    tags = []
    if hasattr(post, 'tag_relations') and post.tag_relations:
        for rel in post.tag_relations:
            if rel.tag:
                tags.append(TagInfoSchema(
                    name=rel.tag.name,
                    display_name=rel.tag.display_name,
                    color=rel.tag.color,
                ))

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
        tags=tags,
        is_active=post.is_active if post.is_active is not None else True,
        llm_status=llm_status,
    )
