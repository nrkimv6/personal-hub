"""크롤링 API 라우트 (요청 및 URL 크롤링 전용).

스케줄 관련 API는 /api/tasks/schedules로 이동됨.
"""

import logging
from datetime import datetime, date
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import CrawlRequest
from app.services.crawl_request_service import CrawlRequestService

# v1에서 가져온 서비스 및 스키마 (pages, url 엔드포인트용)
from app.services.universal_crawl_service import universal_crawl_service
from app.services.universal_crawl_analyzer import UniversalCrawlAnalyzerService
from app.schemas.universal_crawl import (
    CrawlUrlRequest,
    CrawlUrlResponse,
    UniversalCrawlRequestResponse,
    UniversalCrawlRequestList,
    CrawledPageResponse,
    CrawledPageList,
    AnalyzePageResponse,
    AnalysisStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/crawl", tags=["crawl"])


# ============= Request Schemas =============

class CreateCrawlRequestSchema(BaseModel):
    """크롤링 요청 생성 스키마."""
    url: str
    url_type: str
    requested_by: str = "manual"


class CrawlRequestResponse(BaseModel):
    """크롤링 요청 응답 스키마."""
    id: int
    url: str
    url_type: str
    status: str
    requested_by: str
    requested_at: datetime
    picked_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    worker_id: Optional[str] = None
    result_type: Optional[str] = None
    result_id: Optional[int] = None
    error_message: Optional[str] = None
    retry_count: int = 0

    class Config:
        from_attributes = True


class PaginatedRequestsResponse(BaseModel):
    """페이징된 요청 목록 응답."""
    items: list[CrawlRequestResponse]
    total: int
    page: int
    limit: int
    pages: int


class BatchUrlCrawlRequest(BaseModel):
    """복수 URL 배치 크롤링 요청 스키마."""
    urls: List[str] = Field(..., max_length=20, description="크롤링할 URL 목록 (최대 20개)")
    service_account_id: Optional[int] = Field(None, description="서비스 계정 ID (Instagram용)")
    auto_analyze: bool = Field(True, description="자동 분석 여부")
    priority: int = Field(0, description="우선순위 (높을수록 먼저 처리)")


class BatchUrlCrawlResponse(BaseModel):
    """복수 URL 배치 크롤링 응답."""
    created: int = Field(..., description="생성된 요청 수")
    skipped: int = Field(..., description="건너뛴 수 (중복 등)")
    errors: List[str] = Field(default_factory=list, description="오류 메시지 목록")
    request_ids: List[int] = Field(default_factory=list, description="생성된 요청 ID 목록")


# ============= Request Endpoints =============

@router.post("/requests", response_model=CrawlRequestResponse)
async def create_request(
    data: CreateCrawlRequestSchema,
    db: Session = Depends(get_db)
):
    """단건 크롤링 요청 생성."""
    service = CrawlRequestService(db)
    request = service.create_request(
        url=data.url,
        url_type=data.url_type,
        requested_by=data.requested_by
    )
    return request


@router.get("/requests", response_model=PaginatedRequestsResponse)
async def get_requests(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    url_type: Optional[str] = None,
    status: Optional[str] = None,
    requested_by: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """크롤링 요청 목록 조회."""
    service = CrawlRequestService(db)
    result = service.get_requests_paginated(
        page=page,
        limit=limit,
        url_type=url_type,
        status=status,
        requested_by=requested_by
    )
    return PaginatedRequestsResponse(
        items=[CrawlRequestResponse.model_validate(r) for r in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


@router.get("/requests/{request_id}", response_model=CrawlRequestResponse)
async def get_request(
    request_id: int,
    db: Session = Depends(get_db)
):
    """크롤링 요청 상세 조회."""
    service = CrawlRequestService(db)
    request = service.get_request_by_id(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    return request


@router.post("/requests/{request_id}/retry", response_model=CrawlRequestResponse)
async def retry_request(
    request_id: int,
    db: Session = Depends(get_db)
):
    """실패한 요청 재시도."""
    service = CrawlRequestService(db)
    retry = service.retry_failed_request(request_id)
    if not retry:
        raise HTTPException(status_code=400, detail="Cannot retry this request")
    return retry


# ============= URL Crawl Endpoints (from v1) =============

@router.post("/url", response_model=CrawlUrlResponse)
async def create_url_crawl_request(
    body: CrawlUrlRequest,
    db: Session = Depends(get_db),
):
    """
    URL 크롤링 요청 생성

    - Instagram URL은 거부됨 (별도 Instagram 크롤러 사용)
    - URL 타입 자동 감지 (google_form, naver_form, naver_blog, generic)
    - 요청은 pending 상태로 생성되며, 워커가 처리
    """
    try:
        request, message = universal_crawl_service.create_request(
            db=db,
            url=body.url,
            service_account_id=body.service_account_id,
            auto_analyze=body.auto_analyze,
            priority=body.priority,
            requested_by="api",
        )

        return CrawlUrlResponse(
            success=True,
            request_id=request.id,
            url=request.url,
            url_type=request.url_type,
            status=request.status,
            message=message,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"크롤링 요청 생성 실패: {e}")
        raise HTTPException(status_code=500, detail="크롤링 요청 생성에 실패했습니다.")


@router.post("/urls", response_model=BatchUrlCrawlResponse)
async def create_batch_url_crawl_request(
    body: BatchUrlCrawlRequest,
    db: Session = Depends(get_db),
):
    """
    복수 URL 배치 크롤링 요청 생성

    - 최대 20개 URL 동시 요청
    - 모든 URL 타입 지원 (Instagram, Google Form, Naver Blog 등)
    - URL 타입은 자동 감지됨
    - 중복(pending 상태) URL은 자동 스킵
    - OnDemand Worker가 순차 처리
    """
    if len(body.urls) > 20:
        raise HTTPException(status_code=400, detail="최대 20개 URL까지 요청 가능합니다.")

    created = 0
    skipped = 0
    errors: List[str] = []
    request_ids: List[int] = []

    for url in body.urls:
        url = url.strip()
        if not url:
            continue

        try:
            # 이미 pending 상태인 동일 URL 체크
            existing = (
                db.query(CrawlRequest)
                .filter(
                    CrawlRequest.url == url,
                    CrawlRequest.status == CrawlRequest.STATUS_PENDING,
                )
                .first()
            )

            if existing:
                skipped += 1
                continue

            # 크롤링 요청 생성
            request, _ = universal_crawl_service.create_request(
                db=db,
                url=url,
                service_account_id=body.service_account_id,
                auto_analyze=body.auto_analyze,
                priority=body.priority,
                requested_by="batch_api",
            )
            created += 1
            request_ids.append(request.id)

        except ValueError as e:
            errors.append(f"{url}: {str(e)}")
            skipped += 1
        except Exception as e:
            logger.error(f"배치 크롤링 요청 생성 실패 ({url}): {e}")
            errors.append(f"{url}: 요청 생성 실패")
            skipped += 1

    return BatchUrlCrawlResponse(
        created=created,
        skipped=skipped,
        errors=errors,
        request_ids=request_ids,
    )


@router.get("/universal-requests", response_model=UniversalCrawlRequestList)
async def list_universal_crawl_requests(
    status: Optional[str] = Query(None, description="상태 필터 (pending/processing/completed/failed)"),
    url_type: Optional[str] = Query(None, description="URL 타입 필터 (google_form/naver_form/naver_blog/other)"),
    analysis_status: Optional[str] = Query(None, description="분석 상태 필터 (event/uncategorized/unanalyzed)"),
    url_search: Optional[str] = Query(None, description="URL 검색 (부분 일치)"),
    content_search: Optional[str] = Query(None, description="본문 검색 (부분 일치)"),
    date_from: Optional[date] = Query(None, description="요청일 시작 (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="요청일 종료 (YYYY-MM-DD)"),
    sort_by: Optional[str] = Query("requested_at", description="정렬 컬럼 (requested_at/completed_at/url_type)"),
    sort_order: Optional[str] = Query("desc", description="정렬 순서 (asc/desc)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """크롤링 요청 목록 조회 (필터/정렬 지원) - Universal Crawl 전용"""
    return universal_crawl_service.get_requests(
        db=db,
        status=status,
        url_type=url_type,
        analysis_status=analysis_status,
        url_search=url_search,
        content_search=content_search,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.get("/universal-requests/{request_id}", response_model=UniversalCrawlRequestResponse)
async def get_universal_crawl_request(
    request_id: int,
    db: Session = Depends(get_db),
):
    """크롤링 요청 상세 조회 - Universal Crawl 전용"""
    request = universal_crawl_service.get_request(db, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")

    return UniversalCrawlRequestResponse.model_validate(request)


@router.post("/universal-requests/{request_id}/retry", response_model=UniversalCrawlRequestResponse)
async def retry_universal_crawl_request(
    request_id: int,
    db: Session = Depends(get_db),
):
    """실패한 크롤링 요청 재시도 - Universal Crawl 전용"""
    try:
        request = universal_crawl_service.retry_request(db, request_id)
        if not request:
            raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")

        return UniversalCrawlRequestResponse.model_validate(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============= Pages Endpoints (from v1) =============

@router.get("/pages", response_model=CrawledPageList)
async def list_crawled_pages(
    url_type: Optional[str] = Query(None, description="URL 타입 필터"),
    is_event: Optional[bool] = Query(None, description="이벤트 여부 필터"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """크롤링된 페이지 목록 조회"""
    return universal_crawl_service.get_crawled_pages(
        db=db,
        url_type=url_type,
        is_event=is_event,
        page=page,
        page_size=page_size,
    )


@router.get("/pages/{page_id}", response_model=CrawledPageResponse)
async def get_crawled_page(
    page_id: int,
    db: Session = Depends(get_db),
):
    """크롤링된 페이지 상세 조회"""
    page = universal_crawl_service.get_crawled_page(db, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="페이지를 찾을 수 없습니다.")

    return CrawledPageResponse.model_validate(page)


@router.post("/pages/{page_id}/analyze", response_model=AnalyzePageResponse)
async def analyze_page(
    page_id: int,
    db: Session = Depends(get_db),
):
    """
    크롤링된 페이지에 대해 AI 분석 요청

    - 페이지가 존재해야 함
    - 이미 pending/processing 상태인 요청이 있으면 기존 요청 정보 반환
    - LLM Worker가 요청을 처리하며 결과는 crawled_pages.analysis_result에 저장됨
    """
    # 페이지 존재 확인
    page = universal_crawl_service.get_crawled_page(db, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="페이지를 찾을 수 없습니다.")

    # AI 분석 요청 생성
    analyzer = UniversalCrawlAnalyzerService(db)
    request = analyzer.create_analysis_request(page_id, requested_by="api")

    if not request:
        raise HTTPException(status_code=500, detail="AI 분석 요청 생성에 실패했습니다.")

    return AnalyzePageResponse(
        success=True,
        page_id=page_id,
        request_id=request.id,
        status=request.status,
        message="AI 분석 요청이 등록되었습니다." if request.status == "pending" else "이미 분석 요청이 진행 중입니다.",
    )


@router.get("/pages/{page_id}/analysis", response_model=AnalysisStatusResponse)
async def get_analysis_status(
    page_id: int,
    db: Session = Depends(get_db),
):
    """
    페이지의 AI 분석 상태 조회

    - 분석 요청이 없으면 status='not_requested' 반환
    - 분석 완료 시 result에 분석 결과 포함
    """
    # 페이지 존재 확인
    page = universal_crawl_service.get_crawled_page(db, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="페이지를 찾을 수 없습니다.")

    # AI 분석 결과 조회
    analyzer = UniversalCrawlAnalyzerService(db)
    result = analyzer.get_result(page_id)

    if not result:
        return AnalysisStatusResponse(
            page_id=page_id,
            status="not_requested",
        )

    return AnalysisStatusResponse(
        page_id=page_id,
        status=result["status"],
        request_id=result["id"],
        result=result["result"],
        error_message=result["error_message"],
        requested_at=result["requested_at"],
        processed_at=result["processed_at"],
    )
