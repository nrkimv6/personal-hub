"""Instagram module Pydantic schemas."""

from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class ImageInfo(BaseModel):
    """이미지 정보."""
    src: str
    alt: Optional[str] = None


class TagInfoSchema(BaseModel):
    """게시물에 연결된 태그 정보."""
    name: str
    display_name: str
    color: str = "#6b7280"


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
    tags: List[TagInfoSchema] = []

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
    duplicate_stop_count: int = 5  # 연속 중복 시 중단 (0이면 비활성화)


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
    retry_count: int = 0
    retry_of_run_id: Optional[int] = None
    failure_reason: Optional[str] = None

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
    # 고급 설정
    min_interval_hours: int = 2
    duplicate_stop_count: int = 5
    max_retries: int = 3
    retry_interval_minutes: int = 5
    # 계정 지정 (2025-12-21 추가)
    account_id: Optional[int] = None
    account_name: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ScheduleConfigUpdateSchema(BaseModel):
    """스케줄 설정 업데이트."""
    enabled: Optional[bool] = None
    daily_runs: Optional[int] = None
    time_windows: Optional[List[TimeWindow]] = None
    max_posts: Optional[int] = None
    scroll_count: Optional[int] = None
    # 고급 설정
    min_interval_hours: Optional[int] = None
    duplicate_stop_count: Optional[int] = None
    max_retries: Optional[int] = None
    retry_interval_minutes: Optional[int] = None
    # 계정 지정 (2025-12-21 추가)
    account_id: Optional[int] = None


class TodayScheduleItem(BaseModel):
    """오늘 스케줄 항목.

    프론트엔드 InstagramTodayScheduleItem과 일치해야 함.
    """
    scheduled_time: str  # HH:MM 형식
    status: str  # 'pending' | 'running' | 'completed' | 'missed'
    run_id: Optional[int] = None  # 실행 기록 ID (있는 경우)


class StatsSchema(BaseModel):
    """통계 응답."""
    total_posts: int
    today_collected: int
    last_crawl_time: Optional[datetime] = None
    next_crawl_time: Optional[datetime] = None
    accounts_active: int = 0


class CrawlRequestSchema(BaseModel):
    """크롤링 요청 스키마."""
    id: int
    account_id: int
    requested_at: datetime
    requested_by: str = "manual"
    status: str = "pending"
    processed_at: Optional[datetime] = None
    crawl_run_id: Optional[int] = None
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CrawlRequestCreateSchema(BaseModel):
    """크롤링 요청 생성 스키마."""
    account_id: int
    requested_by: str = "manual"


# Worker Status 스키마

class WorkerStatusSchema(BaseModel):
    """워커 상태 응답 스키마."""
    worker_id: str
    pid: Optional[int] = None
    started_at: datetime
    last_heartbeat: datetime
    current_state: str = "idle"  # idle, crawling, processing
    current_account: Optional[str] = None
    current_run_id: Optional[int] = None
    is_alive: bool = True
    # 계산된 필드
    uptime_seconds: int = 0
    heartbeat_age_seconds: int = 0

    model_config = ConfigDict(from_attributes=True)


class WorkerHealthSchema(BaseModel):
    """워커 헬스체크 응답 스키마."""
    status: str  # healthy, warning, dead, no_worker
    worker_id: Optional[str] = None
    last_heartbeat: Optional[datetime] = None
    heartbeat_age_seconds: Optional[int] = None
    current_state: Optional[str] = None
    message: str


# Run 확장 스키마

class RunListParams(BaseModel):
    """실행 기록 조회 파라미터."""
    page: int = 1
    limit: int = 20
    period: Optional[str] = None  # 1d, 7d, 30d, all
    status: Optional[str] = None  # success, failed, all
    account_id: Optional[int] = None


class RunDetailSchema(CrawlRunSchema):
    """실행 기록 상세 스키마."""
    account_name: Optional[str] = None
    duration_seconds: Optional[int] = None
    # 재시도 체인 정보
    retry_chain: List["RunDetailSchema"] = []


class RunListResponse(BaseModel):
    """실행 기록 목록 응답."""
    runs: List[CrawlRunSchema]
    total: int
    page: int
    limit: int


class DailyTrendItem(BaseModel):
    """일별 트렌드 항목."""
    date: str  # YYYY-MM-DD
    total_runs: int
    success_runs: int
    failed_runs: int
    total_collected: int
    new_saved: int


class RunStatsSchema(BaseModel):
    """실행 통계 스키마."""
    total_runs: int
    success_runs: int
    failed_runs: int
    success_rate: float  # 0.0 ~ 1.0
    avg_collected: float
    avg_duration_seconds: float
    daily_trend: List[DailyTrendItem] = []


# ============== 분류 관련 스키마 ==============


class TagSchema(BaseModel):
    """태그 응답 스키마."""
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    color: str = "#6b7280"
    is_active: bool = True
    keyword_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class TagCreateSchema(BaseModel):
    """태그 생성 스키마."""
    name: str
    display_name: str
    description: Optional[str] = None
    color: str = "#6b7280"


class TagUpdateSchema(BaseModel):
    """태그 수정 스키마."""
    display_name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None


class KeywordSchema(BaseModel):
    """키워드 응답 스키마."""
    id: int
    keyword: str
    is_regex: bool = False
    is_case_sensitive: bool = False
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)


class KeywordCreateSchema(BaseModel):
    """키워드 생성 스키마."""
    keyword: str
    is_regex: bool = False
    is_case_sensitive: bool = False


class KeywordBulkCreateSchema(BaseModel):
    """키워드 일괄 생성 스키마."""
    keywords: List[str]


class ClassifyRequestSchema(BaseModel):
    """분류 요청 스키마."""
    post_ids: List[int]


class ClassifyResultSchema(BaseModel):
    """분류 결과 스키마."""
    total: int
    classified: int
    details: List[dict] = []
