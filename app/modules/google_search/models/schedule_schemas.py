"""Google 검색 스케줄 스키마 정의."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class TimeWindow(BaseModel):
    """시간 윈도우."""
    start: str = Field(..., description="시작 시간 (HH:MM)")
    end: str = Field(..., description="종료 시간 (HH:MM)")


class ScheduleValue(BaseModel):
    """스케줄 값 (time_window 타입용)."""
    time_windows: List[TimeWindow] = Field(default_factory=list, description="실행 시간대")
    daily_runs: int = Field(default=1, ge=1, le=24, description="일일 실행 횟수")
    min_interval_hours: int = Field(default=1, ge=1, description="최소 실행 간격 (시간)")
    days: Optional[List[int]] = Field(None, description="실행 요일 (0=일, 1=월, ..., 6=토)")


class GoogleSearchScheduleCreate(BaseModel):
    """Google 검색 스케줄 생성 요청."""
    saved_search_id: int = Field(..., description="저장된 검색 ID")
    display_name: Optional[str] = Field(None, description="표시 이름")
    schedule_type: str = Field(default="time_window", description="스케줄 타입 (time_window 또는 cron)")
    schedule_value: ScheduleValue = Field(..., description="스케줄 설정")
    enabled: bool = Field(default=True, description="활성화 여부")


class GoogleSearchScheduleUpdate(BaseModel):
    """Google 검색 스케줄 수정 요청."""
    display_name: Optional[str] = None
    schedule_value: Optional[ScheduleValue] = None
    enabled: Optional[bool] = None


class GoogleSearchScheduleResponse(BaseModel):
    """Google 검색 스케줄 응답."""
    id: int
    name: str
    display_name: Optional[str]
    target_type: str
    target_config: dict
    schedule_type: str
    schedule_value: dict
    enabled: bool
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    # 저장된 검색 정보 (조인)
    saved_search_name: Optional[str] = None
    saved_search_query: Optional[str] = None

    model_config = {"from_attributes": True}


class ScheduleRunResponse(BaseModel):
    """스케줄 실행 이력 응답."""
    id: int
    schedule_id: int
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    collected_count: int
    saved_count: int
    stop_reason: Optional[str]
    error_message: Optional[str]
    duration_seconds: Optional[int]
    search_id: Optional[str] = None

    model_config = {"from_attributes": True}


class ScheduleRunListResponse(BaseModel):
    """스케줄 실행 이력 목록 응답."""
    items: List[ScheduleRunResponse]
    total: int
    page: int
    limit: int
    pages: int


class ScheduleSearchResultItem(BaseModel):
    """스케줄 검색 결과 항목."""
    rank: int
    title: str
    url: str
    display_url: Optional[str] = None
    snippet: Optional[str] = None
    publish_date: Optional[str] = None


class ScheduleSearchHistoryItem(BaseModel):
    """스케줄 검색 히스토리 항목 (결과 포함)."""
    search_id: str
    query: str
    date_filter: Optional[str] = None
    status: str
    total_results: int
    created_at: datetime
    completed_at: Optional[datetime] = None
    results: List[ScheduleSearchResultItem] = Field(default_factory=list)


class ScheduleSearchResultsResponse(BaseModel):
    """스케줄별 검색 결과 목록 응답."""
    schedule_id: int
    schedule_name: Optional[str] = None
    saved_search_name: Optional[str] = None
    query: Optional[str] = None
    items: List[ScheduleSearchHistoryItem]
    total: int
    page: int
    limit: int


class ScheduleRecentResultItem(BaseModel):
    """전체 스케줄 최근 결과 요약 항목."""
    schedule_id: int
    schedule_name: Optional[str] = None
    saved_search_name: Optional[str] = None
    query: Optional[str] = None
    enabled: bool
    last_search: Optional[ScheduleSearchHistoryItem] = None
    last_run_at: Optional[datetime] = None
