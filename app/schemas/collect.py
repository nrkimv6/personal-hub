"""수집 관리 스키마."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class CollectedPostBase(BaseModel):
    """수집된 게시물 기본 스키마."""

    id: int
    source_type: str  # 'instagram' | 'web'
    source_id: int    # 원본 테이블 ID

    # 공통 필드
    title: Optional[str] = None
    content: Optional[str] = None
    thumbnail: Optional[str] = None
    url: str
    url_type: str  # 'instagram_post', 'google_form', 'naver_blog', ...
    created_at: datetime
    classification: Optional[str] = None  # 'event', 'popup', 'uncategorized', None

    # Instagram 전용
    shortcode: Optional[str] = None
    account_name: Optional[str] = None
    is_active: Optional[bool] = None
    tags: Optional[List[str]] = None

    # Web 전용
    extractor_used: Optional[str] = None
    is_event: Optional[bool] = None

    # AI 분석 상태 (Instagram 전용)
    llm_status: Optional[str] = None  # pending | processing | completed | failed

    class Config:
        from_attributes = True


class CollectedPostList(BaseModel):
    """수집된 게시물 목록 응답."""

    items: List[CollectedPostBase]
    total: int
    page: int
    limit: int
    total_pages: int


class CollectedPostFilters(BaseModel):
    """수집된 게시물 필터."""

    source_type: Optional[str] = None  # 'instagram', 'web', None(전체)
    url_type: Optional[str] = None
    classification: Optional[str] = None  # 'event', 'popup', 'uncategorized', 'unclassified'
    search: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    is_active: Optional[bool] = None  # Instagram 전용


class CrawlHistoryItem(BaseModel):
    """워커 실행 이력 항목."""

    id: int
    history_type: str  # 'request' | 'schedule_run' | 'google_search'

    # 공통 필드
    source_type: str  # 'instagram' | 'web' | 'google_search' | 'activity' | 'writing' | 'report'
    status: str  # 'pending', 'processing', 'completed', 'failed'
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    error_message: Optional[str] = None

    # Request / Google Search 전용
    url: Optional[str] = None
    url_type: Optional[str] = None
    request_type: Optional[str] = None  # 'feed', 'single_post', 'single_post_url'
    requested_by: Optional[str] = None  # 'manual', 'schedule', 'retry'

    # Schedule Run / Google Search 전용
    schedule_id: Optional[int] = None
    schedule_name: Optional[str] = None
    collected_count: int = 0
    saved_count: int = 0
    created_count: int = 0  # 신규 추가
    updated_count: int = 0  # 업데이트
    unchanged_count: int = 0  # 중복 (변경없음)

    class Config:
        from_attributes = True


class CrawlHistoryList(BaseModel):
    """워커 실행 이력 목록 응답."""

    items: List[CrawlHistoryItem]
    total: int
    page: int
    limit: int
    total_pages: int


class CrawlHistoryStats(BaseModel):
    """워커 실행 이력 통계."""

    total_requests: int = 0
    completed_requests: int = 0
    failed_requests: int = 0
    processing_requests: int = 0
