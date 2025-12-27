"""
Universal Crawl 스키마 (Pydantic) - 범용 URL 크롤링 요청 관리
"""
import json
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional, Literal


# URL 타입 정의
UrlType = Literal["google_form", "naver_form", "naver_blog", "generic", "other"]

# 요청 상태 정의
CrawlStatus = Literal["pending", "processing", "completed", "failed"]

# 요청 출처 정의
RequestedBy = Literal["manual", "pwa_share", "api"]


class CrawledPageBase(BaseModel):
    """CrawledPage 기본 스키마"""
    url: str
    url_type: UrlType


class CrawledPageCreate(CrawledPageBase):
    """CrawledPage 생성 스키마"""
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    extracted_data: Optional[dict] = None
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image: Optional[str] = None
    extractor_used: Optional[str] = None
    url_hash: str


class CrawledPageResponse(CrawledPageBase):
    """CrawledPage 응답 스키마"""
    id: int
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    extracted_data: Optional[dict] = None
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image: Optional[str] = None
    crawled_at: datetime
    extractor_used: Optional[str] = None
    is_event: Optional[bool] = None
    event_id: Optional[int] = None
    analysis_result: Optional[dict] = None
    url_hash: Optional[str] = None

    @field_validator('extracted_data', 'analysis_result', mode='before')
    @classmethod
    def parse_json_dict(cls, v):
        """JSON 문자열을 dict로 변환"""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    class Config:
        from_attributes = True


class UniversalCrawlRequestCreate(BaseModel):
    """UniversalCrawlRequest 생성 스키마"""
    url: str
    url_type: Optional[UrlType] = None  # 자동 감지 가능
    service_account_id: Optional[int] = None  # 브라우저 프로필, 없으면 기본/HTTP
    auto_analyze: bool = True
    priority: int = 0
    requested_by: RequestedBy = "manual"
    extra_metadata: Optional[dict] = None


class UniversalCrawlRequestUpdate(BaseModel):
    """UniversalCrawlRequest 수정 스키마"""
    status: Optional[CrawlStatus] = None
    error_message: Optional[str] = None
    retry_count: Optional[int] = None
    crawled_page_id: Optional[int] = None


class UniversalCrawlRequestResponse(BaseModel):
    """UniversalCrawlRequest 응답 스키마"""
    id: int
    url: str
    url_type: str
    service_account_id: Optional[int] = None
    status: CrawlStatus
    requested_by: str
    requested_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int
    crawled_page_id: Optional[int] = None
    auto_analyze: bool
    priority: int
    extra_metadata: Optional[dict] = None

    # 크롤링 결과 (조인 시)
    crawled_page: Optional[CrawledPageResponse] = None

    @field_validator('extra_metadata', mode='before')
    @classmethod
    def parse_json_metadata(cls, v):
        """JSON 문자열을 dict로 변환"""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    class Config:
        from_attributes = True


class UniversalCrawlRequestList(BaseModel):
    """UniversalCrawlRequest 목록 응답"""
    items: list[UniversalCrawlRequestResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class CrawledPageList(BaseModel):
    """CrawledPage 목록 응답"""
    items: list[CrawledPageResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class CrawlUrlRequest(BaseModel):
    """URL 크롤링 요청 (API 엔드포인트용)"""
    url: str
    service_account_id: Optional[int] = None
    auto_analyze: bool = True
    priority: int = 0


class CrawlUrlResponse(BaseModel):
    """URL 크롤링 요청 응답"""
    success: bool
    request_id: int
    url: str
    url_type: str
    status: CrawlStatus
    message: str


class AnalyzePageRequest(BaseModel):
    """페이지 AI 분석 요청 (선택적 바디)"""
    pass  # 현재는 바디 없이 page_id만 사용


class AnalyzePageResponse(BaseModel):
    """페이지 AI 분석 응답"""
    success: bool
    page_id: int
    request_id: int
    status: str
    message: str


class AnalysisStatusResponse(BaseModel):
    """AI 분석 상태 응답"""
    page_id: int
    status: str  # pending, processing, completed, failed, not_requested
    request_id: Optional[int] = None
    result: Optional[dict] = None
    error_message: Optional[str] = None
    requested_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
