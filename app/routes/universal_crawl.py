"""
Universal Crawl API 라우트 - 범용 URL 크롤링 요청 관리
"""
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
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

router = APIRouter(prefix="/api/v1/crawl", tags=["universal-crawl"])


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
    """크롤링 요청 목록 조회 (필터/정렬 지원)"""
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
