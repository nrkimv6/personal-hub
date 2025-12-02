"""
Business 스키마 (Pydantic)
설계 문서: 2025-12-01_monitoring_restructure_design.md
업데이트: 2025-12-03 - GraphQL API 상세정보 필드 추가 (REQ-DATA-004)
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
    place_id: Optional[str] = None
    name: str
    service_type: str = "naver"
    category: Optional[str] = None
    service_name: Optional[str] = None
    # 위치 정보
    road_address: Optional[str] = None
    jibun_address: Optional[str] = None
    detail_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = None
    # 설정
    booking_options: Optional[Dict[str, Any]] = None
    is_enabled: bool = True


class BusinessCreate(BusinessBase):
    """Business 생성 스키마"""
    pass


class BusinessUpdate(BaseModel):
    """Business 수정 스키마"""
    name: Optional[str] = None
    business_type_id: Optional[int] = None
    place_id: Optional[str] = None
    category: Optional[str] = None
    service_name: Optional[str] = None
    road_address: Optional[str] = None
    jibun_address: Optional[str] = None
    detail_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = None
    booking_options: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None


class Business(BusinessBase):
    """Business 응답 스키마"""
    id: int
    api_synced_at: Optional[datetime] = None
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
    item_name: Optional[str] = None  # 없으면 API에서 자동 조회
    business_name: Optional[str] = None  # 없으면 API에서 자동 조회
    auto_booking_enabled: bool = False
    time_range: Optional[str] = None
    max_bookings_per_schedule: int = 1
    fetch_details: bool = True  # GraphQL API로 상세정보 조회 여부


class UrlImportResponse(BaseModel):
    """URL 기반 임포트 응답 스키마"""
    success: bool
    message: str
    business_id: Optional[int] = None
    item_id: Optional[int] = None
    schedule_id: Optional[int] = None
    parsed_info: Optional[Dict[str, Any]] = None
    # 조회된 상세정보
    business_details: Optional[Dict[str, Any]] = None
    item_details: Optional[Dict[str, Any]] = None
