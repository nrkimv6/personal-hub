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
