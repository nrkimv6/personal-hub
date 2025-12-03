"""
BizItem 스키마 (Pydantic)
설계 문서: 2025-12-01_monitoring_restructure_design.md
업데이트: 2025-12-03 - GraphQL API 상세정보 필드 추가 (REQ-DATA-004)
"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.monitor_schedule import MonitorSchedule


class BizItemBase(BaseModel):
    """BizItem 기본 스키마"""
    biz_item_id: str
    name: str
    base_url: Optional[str] = None
    description: Optional[str] = None
    # 아이템 상세정보 (REQ-DATA-004)
    biz_item_type: Optional[str] = None
    biz_item_sub_type: Optional[str] = None
    booking_count_type: Optional[str] = None
    min_booking_count: Optional[int] = None
    max_booking_count: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    extra_desc_json: Optional[str] = None
    booking_precaution_json: Optional[str] = None
    # 설정
    is_enabled: bool = True
    time_range: Optional[str] = None
    auto_booking_enabled: bool = False
    max_bookings_per_schedule: int = 1
    booking_options_override: Optional[Dict[str, Any]] = None


class BizItemCreate(BizItemBase):
    """BizItem 생성 스키마"""
    business_id: Optional[int] = None  # FK - route에서 설정됨
    # DEPRECATED: account_id moved to MonitorSchedule (2025-12-03)


class BizItemUpdate(BaseModel):
    """BizItem 수정 스키마"""
    name: Optional[str] = None
    base_url: Optional[str] = None
    description: Optional[str] = None
    biz_item_type: Optional[str] = None
    biz_item_sub_type: Optional[str] = None
    booking_count_type: Optional[str] = None
    min_booking_count: Optional[int] = None
    max_booking_count: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    extra_desc_json: Optional[str] = None
    booking_precaution_json: Optional[str] = None
    is_enabled: Optional[bool] = None
    time_range: Optional[str] = None
    auto_booking_enabled: Optional[bool] = None
    max_bookings_per_schedule: Optional[int] = None
    booking_options_override: Optional[Dict[str, Any]] = None
    # DEPRECATED: account_id moved to MonitorSchedule (2025-12-03)


class BizItem(BizItemBase):
    """BizItem 응답 스키마"""
    id: int
    business_id: int
    # DEPRECATED: account_id moved to MonitorSchedule (2025-12-03)
    api_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BizItemWithSchedules(BizItem):
    """BizItem + 일정 목록 응답 스키마"""
    schedules: List["MonitorSchedule"] = []

    class Config:
        from_attributes = True


# Forward reference 해결
from app.schemas.monitor_schedule import MonitorSchedule
BizItemWithSchedules.model_rebuild()
