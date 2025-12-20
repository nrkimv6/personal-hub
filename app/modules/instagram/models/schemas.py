"""Instagram module Pydantic schemas."""

from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class ImageInfo(BaseModel):
    """이미지 정보."""
    src: str
    alt: Optional[str] = None


class PostSchema(BaseModel):
    """게시물 응답 스키마."""
    id: int
    post_id: str
    account: Optional[str] = None
    url: Optional[str] = None
    caption: Optional[str] = None
    images: List[ImageInfo] = []
    posted_at: Optional[datetime] = None
    display_time: Optional[str] = None
    is_ad: bool = False
    collected_at: datetime
    crawl_run_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class PostCreateSchema(BaseModel):
    """게시물 생성 스키마."""
    post_id: str
    account: Optional[str] = None
    url: Optional[str] = None
    caption: Optional[str] = None
    images: List[ImageInfo] = []
    posted_at: Optional[datetime] = None
    display_time: Optional[str] = None
    is_ad: bool = False


class PostListResponse(BaseModel):
    """게시물 목록 응답."""
    posts: List[PostSchema]
    total: int
    page: int
    limit: int


class CrawlOptionsSchema(BaseModel):
    """크롤링 옵션."""
    max_posts: int = 20
    scroll_count: int = 3


class CrawlResponse(BaseModel):
    """크롤링 응답."""
    success: bool
    total_collected: int
    new_saved: int
    crawl_run_id: Optional[int] = None
    message: Optional[str] = None


class CrawlRunSchema(BaseModel):
    """크롤링 실행 기록."""
    id: int
    account_id: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    success: bool
    total_collected: int
    new_saved: int
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TimeWindow(BaseModel):
    """시간대 설정."""
    start: str  # "HH:MM"
    end: str    # "HH:MM"


class ScheduleConfigSchema(BaseModel):
    """스케줄 설정 응답."""
    id: int
    enabled: bool = True
    daily_runs: int = 3
    time_windows: List[TimeWindow] = []
    max_posts: int = 20
    scroll_count: int = 3
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ScheduleConfigUpdateSchema(BaseModel):
    """스케줄 설정 업데이트."""
    enabled: Optional[bool] = None
    daily_runs: Optional[int] = None
    time_windows: Optional[List[TimeWindow]] = None
    max_posts: Optional[int] = None
    scroll_count: Optional[int] = None


class TodayScheduleItem(BaseModel):
    """오늘 스케줄 항목."""
    time: str
    completed: bool


class StatsSchema(BaseModel):
    """통계 응답."""
    total_posts: int
    today_collected: int
    last_crawl_time: Optional[datetime] = None
    next_crawl_time: Optional[datetime] = None
    accounts_active: int = 0
