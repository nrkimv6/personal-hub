"""
BizItem 스키마 (Pydantic)
설계 문서: 2025-12-01_monitoring_restructure_design.md
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
    time_range: Optional[str] = None
    auto_booking_enabled: bool = False
    max_bookings_per_schedule: int = 1
    booking_options_override: Optional[Dict[str, Any]] = None


class BizItemCreate(BizItemBase):
    """BizItem 생성 스키마"""
    business_id: int  # FK


class BizItemUpdate(BaseModel):
    """BizItem 수정 스키마"""
    name: Optional[str] = None
    base_url: Optional[str] = None
    time_range: Optional[str] = None
    auto_booking_enabled: Optional[bool] = None
    max_bookings_per_schedule: Optional[int] = None
    booking_options_override: Optional[Dict[str, Any]] = None


class BizItem(BizItemBase):
    """BizItem 응답 스키마"""
    id: int
    business_id: int
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
