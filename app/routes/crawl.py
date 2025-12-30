"""크롤링 API 라우트 (통합)."""

import logging
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import CrawlRequest, CrawlSchedule, CrawlScheduleRun
from app.services.crawl_request_service import CrawlRequestService
from app.services.crawl_schedule_service import CrawlScheduleService

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


# ============= Schedule Schemas =============

class CreateScheduleSchema(BaseModel):
    """스케줄 생성 스키마."""
    name: str
    target_type: str
    schedule_type: str
    display_name: Optional[str] = None
    target_config: Optional[dict] = None
    schedule_value: Optional[str] = None
    enabled: bool = True


class UpdateScheduleSchema(BaseModel):
    """스케줄 업데이트 스키마."""
    display_name: Optional[str] = None
    target_config: Optional[dict] = None
    schedule_value: Optional[str] = None
    enabled: Optional[bool] = None


class ScheduleResponse(BaseModel):
    """스케줄 응답 스키마."""
    id: int
    name: str
    display_name: Optional[str] = None
    target_type: str
    target_config: Optional[dict] = None
    schedule_type: str
    schedule_value: Optional[str] = None
    enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ScheduleRunResponse(BaseModel):
    """스케줄 실행 응답 스키마."""
    id: int
    schedule_id: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str
    collected_count: int = 0
    saved_count: int = 0
    stop_reason: Optional[str] = None
    error_message: Optional[str] = None
    worker_id: Optional[str] = None
    duration_seconds: Optional[int] = None

    class Config:
        from_attributes = True


class PaginatedRunsResponse(BaseModel):
    """페이징된 실행 목록 응답."""
    items: list[ScheduleRunResponse]
    total: int
    page: int
    limit: int
    pages: int


class RunStatsResponse(BaseModel):
    """실행 통계 응답."""
    period_days: int
    total_runs: int
    completed_runs: int
    failed_runs: int
    success_rate: float
    total_collected: int
    total_saved: int


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


# ============= Schedule Endpoints =============

@router.post("/schedules", response_model=ScheduleResponse)
async def create_schedule(
    data: CreateScheduleSchema,
    db: Session = Depends(get_db)
):
    """스케줄 생성."""
    service = CrawlScheduleService(db)

    # 중복 이름 체크
    existing = service.get_schedule_by_name(data.name)
    if existing:
        raise HTTPException(status_code=400, detail="Schedule name already exists")

    schedule = service.create_schedule(
        name=data.name,
        target_type=data.target_type,
        schedule_type=data.schedule_type,
        display_name=data.display_name,
        target_config=data.target_config,
        schedule_value=data.schedule_value,
        enabled=data.enabled
    )
    return _schedule_to_response(schedule)


@router.get("/schedules")
async def get_schedules(
    target_type: Optional[str] = None,
    enabled_only: bool = True,
    db: Session = Depends(get_db)
):
    """스케줄 목록 조회."""
    service = CrawlScheduleService(db)

    if target_type:
        schedules = service.get_schedules_by_type(target_type, enabled_only)
    else:
        query = db.query(CrawlSchedule)
        if enabled_only:
            query = query.filter(CrawlSchedule.enabled == True)
        schedules = query.all()

    return [_schedule_to_response(s) for s in schedules]


@router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: int,
    db: Session = Depends(get_db)
):
    """스케줄 상세 조회."""
    service = CrawlScheduleService(db)
    schedule = service.get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _schedule_to_response(schedule)


@router.put("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: int,
    data: UpdateScheduleSchema,
    db: Session = Depends(get_db)
):
    """스케줄 업데이트."""
    service = CrawlScheduleService(db)

    updates = data.model_dump(exclude_unset=True)
    schedule = service.update_schedule(schedule_id, **updates)

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _schedule_to_response(schedule)


@router.post("/schedules/{schedule_id}/toggle")
async def toggle_schedule(
    schedule_id: int,
    enabled: bool = Query(...),
    db: Session = Depends(get_db)
):
    """스케줄 활성화/비활성화."""
    service = CrawlScheduleService(db)
    schedule = service.toggle_schedule(schedule_id, enabled)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"success": True, "enabled": schedule.enabled}


# ============= Schedule Run Endpoints =============

@router.get("/schedules/{schedule_id}/runs", response_model=PaginatedRunsResponse)
async def get_schedule_runs(
    schedule_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """스케줄 실행 이력 조회."""
    service = CrawlScheduleService(db)

    # 스케줄 존재 확인
    schedule = service.get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    result = service.get_runs_paginated(
        schedule_id=schedule_id,
        page=page,
        limit=limit,
        status=status
    )
    return PaginatedRunsResponse(
        items=[_run_to_response(r) for r in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


@router.get("/schedules/{schedule_id}/stats", response_model=RunStatsResponse)
async def get_schedule_stats(
    schedule_id: int,
    days: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """스케줄 실행 통계 조회."""
    service = CrawlScheduleService(db)

    # 스케줄 존재 확인
    schedule = service.get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    stats = service.get_run_stats(schedule_id=schedule_id, days=days)
    return stats


@router.get("/runs", response_model=PaginatedRunsResponse)
async def get_all_runs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """전체 실행 이력 조회."""
    service = CrawlScheduleService(db)
    result = service.get_runs_paginated(
        page=page,
        limit=limit,
        status=status
    )
    return PaginatedRunsResponse(
        items=[_run_to_response(r) for r in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


# ============= Helper Functions =============

def _schedule_to_response(schedule: CrawlSchedule) -> ScheduleResponse:
    """스케줄을 응답 스키마로 변환."""
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        display_name=schedule.display_name,
        target_type=schedule.target_type,
        target_config=schedule.get_target_config(),
        schedule_type=schedule.schedule_type,
        schedule_value=schedule.schedule_value,
        enabled=schedule.enabled,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at
    )


def _run_to_response(run: CrawlScheduleRun) -> ScheduleRunResponse:
    """실행을 응답 스키마로 변환."""
    return ScheduleRunResponse(
        id=run.id,
        schedule_id=run.schedule_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        collected_count=run.collected_count,
        saved_count=run.saved_count,
        stop_reason=run.stop_reason,
        error_message=run.error_message,
        worker_id=run.worker_id,
        duration_seconds=run.duration_seconds
    )


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
