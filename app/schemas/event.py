"""
Event 스키마 (Pydantic) - 독립 이벤트 관리
"""
import json
from pydantic import BaseModel, field_validator, computed_field
from datetime import datetime, date
from typing import Optional, List, Literal


class EventBase(BaseModel):
    """Event 기본 스키마"""
    title: str
    event_type: Literal["event", "popup", "ambassador", "other"] = "event"
    event_url: Optional[str] = None
    url_type: Optional[str] = None  # google_form/naver_form/shop/survey/other
    additional_urls: List[str] = []
    event_start: Optional[date] = None
    event_end: Optional[date] = None
    announcement_date: Optional[date] = None
    organizer: Optional[str] = None
    summary: Optional[str] = None
    prizes: List[str] = []
    winner_count: Optional[int] = None
    purchase_required: Optional[str] = None  # yes_all/yes_partial/no
    location_venue: Optional[str] = None
    location_address: Optional[str] = None
    source_type: Literal["instagram", "manual", "web", "other"] = "manual"
    source_url: Optional[str] = None
    source_note: Optional[str] = None
    user_note: Optional[str] = None


class EventCreate(EventBase):
    """Event 생성 스키마"""
    source_instagram_post_id: Optional[int] = None


class EventUpdate(BaseModel):
    """Event 수정 스키마 - 모든 필드 optional"""
    title: Optional[str] = None
    event_type: Optional[Literal["event", "popup", "ambassador", "other"]] = None
    status: Optional[Literal["active", "ended", "cancelled"]] = None
    event_url: Optional[str] = None
    url_type: Optional[str] = None
    additional_urls: Optional[List[str]] = None
    event_start: Optional[date] = None
    event_end: Optional[date] = None
    announcement_date: Optional[date] = None
    organizer: Optional[str] = None
    summary: Optional[str] = None
    prizes: Optional[List[str]] = None
    winner_count: Optional[int] = None
    purchase_required: Optional[str] = None
    location_venue: Optional[str] = None
    location_address: Optional[str] = None
    source_type: Optional[Literal["instagram", "manual", "web", "other"]] = None
    source_instagram_post_id: Optional[int] = None
    source_url: Optional[str] = None
    source_note: Optional[str] = None
    user_note: Optional[str] = None
    is_bookmarked: Optional[bool] = None
    is_participated: Optional[bool] = None


class EventResponse(EventBase):
    """Event 응답 스키마"""
    id: int
    status: str
    is_bookmarked: bool
    is_participated: bool
    source_instagram_post_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    # Instagram 출처 정보 (연결된 경우)
    source_instagram_url: Optional[str] = None
    source_instagram_account: Optional[str] = None

    @field_validator('prizes', 'additional_urls', mode='before')
    @classmethod
    def parse_json_list(cls, v):
        """JSON 문자열을 리스트로 변환"""
        if v is None:
            return []
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v

    @computed_field
    @property
    def event_status(self) -> str:
        """이벤트 진행 상태 계산 (ongoing/upcoming/ended)"""
        if self.status == "cancelled":
            return "cancelled"

        today = date.today()

        # 종료일 기준
        if self.event_end:
            if self.event_end < today:
                return "ended"

        # 시작일 기준
        if self.event_start:
            if self.event_start > today:
                return "upcoming"

        # 시작일이 없거나 오늘 이전이고, 종료일이 없거나 오늘 이후
        return "ongoing"

    @computed_field
    @property
    def days_remaining(self) -> Optional[int]:
        """종료일까지 남은 일수"""
        if not self.event_end:
            return None
        today = date.today()
        delta = self.event_end - today
        return delta.days

    class Config:
        from_attributes = True


class EventList(BaseModel):
    """Event 목록 응답"""
    items: List[EventResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class EventImportFromInstagram(BaseModel):
    """Instagram에서 이벤트 가져오기 요청"""
    instagram_post_id: int
    title: Optional[str] = None  # 제목 재정의 (없으면 llm_summary 사용)
