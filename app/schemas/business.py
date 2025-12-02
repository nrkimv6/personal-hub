"""
Business 스키마 (Pydantic)
설계 문서: 2025-12-01_monitoring_restructure_design.md
"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.biz_item import BizItem


class BusinessBase(BaseModel):
    """Business 기본 스키마"""
    business_id: str
    business_type_id: Optional[int] = None
    name: str
    service_type: str = "naver"
    category: Optional[str] = None
    booking_options: Optional[Dict[str, Any]] = None
    is_enabled: bool = True


class BusinessCreate(BusinessBase):
    """Business 생성 스키마"""
    pass


class BusinessUpdate(BaseModel):
    """Business 수정 스키마"""
    name: Optional[str] = None
    business_type_id: Optional[int] = None
    category: Optional[str] = None
    booking_options: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None


class Business(BusinessBase):
    """Business 응답 스키마"""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BusinessWithItems(Business):
    """Business + 아이템 목록 응답 스키마"""
    items: List["BizItem"] = []

    class Config:
        from_attributes = True


# Forward reference 해결
from app.schemas.biz_item import BizItem
BusinessWithItems.model_rebuild()


class UrlImportRequest(BaseModel):
    """URL 기반 임포트 요청 스키마"""
    url: str
    item_name: str
    business_name: Optional[str] = None  # 없으면 자동 생성
    auto_booking_enabled: bool = False
    time_range: Optional[str] = None
    max_bookings_per_schedule: int = 1


class UrlImportResponse(BaseModel):
    """URL 기반 임포트 응답 스키마"""
    success: bool
    message: str
    business_id: Optional[int] = None
    item_id: Optional[int] = None
    schedule_id: Optional[int] = None
    parsed_info: Optional[Dict[str, Any]] = None
