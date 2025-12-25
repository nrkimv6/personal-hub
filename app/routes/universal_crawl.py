"""
Universal Crawl API 라우트 - 범용 URL 크롤링 요청 관리
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.universal_crawl_service import universal_crawl_service
from app.schemas.universal_crawl import (
    CrawlUrlRequest,
    CrawlUrlResponse,
    UniversalCrawlRequestResponse,
    UniversalCrawlRequestList,
    CrawledPageResponse,
    CrawledPageList,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crawl", tags=["universal-crawl"])


@router.post("/url", response_model=CrawlUrlResponse)
async def create_crawl_request(
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
            account_id=body.account_id,
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


@router.get("/requests", response_model=UniversalCrawlRequestList)
async def list_crawl_requests(
    status: Optional[str] = Query(None, description="상태 필터 (pending/processing/completed/failed)"),
    url_type: Optional[str] = Query(None, description="URL 타입 필터"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """크롤링 요청 목록 조회"""
    return universal_crawl_service.get_requests(
        db=db,
        status=status,
        url_type=url_type,
        page=page,
        page_size=page_size,
    )


@router.get("/requests/{request_id}", response_model=UniversalCrawlRequestResponse)
async def get_crawl_request(
    request_id: int,
    db: Session = Depends(get_db),
):
    """크롤링 요청 상세 조회"""
    request = universal_crawl_service.get_request(db, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")

    return UniversalCrawlRequestResponse.model_validate(request)


@router.post("/requests/{request_id}/retry", response_model=UniversalCrawlRequestResponse)
async def retry_crawl_request(
    request_id: int,
    db: Session = Depends(get_db),
):
    """실패한 크롤링 요청 재시도"""
    try:
        request = universal_crawl_service.retry_request(db, request_id)
        if not request:
            raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")

        return UniversalCrawlRequestResponse.model_validate(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
