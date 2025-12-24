"""
Popup 스키마 (Pydantic) - 팝업스토어 관리
"""
import json
from pydantic import BaseModel, field_validator, computed_field
from datetime import datetime, date
from typing import Optional, List, Literal


class PopupBase(BaseModel):
    """Popup 기본 스키마"""
    title: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    # 위치 정보
    venue_name: Optional[str] = None
    address: Optional[str] = None
    floor_info: Optional[str] = None

    # 운영 정보
    operating_hours: Optional[str] = None
    admission_fee: Optional[str] = None
    reservation_required: bool = False
    reservation_url: Optional[str] = None

    # 브랜드/주최
    brand: Optional[str] = None
    organizer: Optional[str] = None
    collaboration: Optional[str] = None

    # 상세
    summary: Optional[str] = None
    highlights: List[str] = []
    official_url: Optional[str] = None
    additional_urls: List[str] = []

    # 출처
    source_type: Literal["instagram", "manual", "web"] = "manual"
    user_note: Optional[str] = None
    input_source: Literal["ai", "human", "ai_edited"] = "human"  # 입력 출처


class PopupCreate(PopupBase):
    """Popup 생성 스키마"""
    source_instagram_post_id: Optional[int] = None
    source_instagram_url: Optional[str] = None
    source_instagram_account: Optional[str] = None
    thumbnail_url: Optional[str] = None


class PopupUpdate(BaseModel):
    """Popup 수정 스키마 - 모든 필드 optional"""
    title: Optional[str] = None
    thumbnail_url: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    venue_name: Optional[str] = None
    address: Optional[str] = None
    floor_info: Optional[str] = None

    operating_hours: Optional[str] = None
    admission_fee: Optional[str] = None
    reservation_required: Optional[bool] = None
    reservation_url: Optional[str] = None

    brand: Optional[str] = None
    organizer: Optional[str] = None
    collaboration: Optional[str] = None

    summary: Optional[str] = None
    highlights: Optional[List[str]] = None
    official_url: Optional[str] = None
    additional_urls: Optional[List[str]] = None

    source_type: Optional[Literal["instagram", "manual", "web"]] = None
    user_note: Optional[str] = None
    status: Optional[Literal["active", "ended", "cancelled"]] = None
    is_bookmarked: Optional[bool] = None
    is_visited: Optional[bool] = None
    input_source: Optional[Literal["ai", "human", "ai_edited"]] = None


class PopupResponse(PopupBase):
    """Popup 응답 스키마"""
    id: int
    thumbnail_url: Optional[str] = None
    status: str
    is_bookmarked: bool
    is_visited: bool
    source_instagram_post_id: Optional[int] = None
    source_instagram_url: Optional[str] = None
    source_instagram_account: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_validator('highlights', 'additional_urls', mode='before')
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
    def popup_status(self) -> str:
        """팝업 진행 상태 계산 (ongoing/upcoming/ended)"""
        if self.status == "cancelled":
            return "cancelled"

        today = date.today()

        if self.end_date:
            if self.end_date < today:
                return "ended"

        if self.start_date:
            if self.start_date > today:
                return "upcoming"

        return "ongoing"

    @computed_field
    @property
    def days_remaining(self) -> Optional[int]:
        """종료일까지 남은 일수"""
        if not self.end_date:
            return None
        today = date.today()
        delta = self.end_date - today
        return delta.days

    class Config:
        from_attributes = True


class PopupList(BaseModel):
    """Popup 목록 응답"""
    items: List[PopupResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class PopupImportFromInstagram(BaseModel):
    """Instagram에서 팝업 가져오기 요청"""
    instagram_post_id: int
    title: Optional[str] = None
