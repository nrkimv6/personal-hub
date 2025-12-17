"""
슬롯 조회 API 스키마
작성일: 2025-12-16
요구사항: REQ-MON-012 (슬롯 조회 API)
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class SlotCheckBusinessInfo(BaseModel):
    """업체 정보"""
    business_id: str
    name: str
    business_type_id: Optional[int] = None


class SlotCheckBizItemInfo(BaseModel):
    """상품 정보"""
    biz_item_id: str
    name: str


class SlotInfo(BaseModel):
    """개별 슬롯 정보"""
    time: str = Field(..., description="시간 (HH:MM)")
    capacity: int = Field(..., description="정원 (unit_stock)")
    booked: int = Field(..., description="예약됨 (unit_booking_count)")
    remaining: int = Field(..., description="남음 (capacity - booked)")
    is_available: bool = Field(..., description="예약 가능 여부")


class DateSummary(BaseModel):
    """날짜별 요약"""
    total_capacity: int = Field(..., description="총 정원")
    total_booked: int = Field(..., description="총 예약됨")
    total_remaining: int = Field(..., description="총 남음")


class DateSlots(BaseModel):
    """날짜별 슬롯 정보"""
    date: str = Field(..., description="날짜 (YYYY-MM-DD)")
    day_of_week: str = Field(..., description="요일 (월/화/수/목/금/토/일)")
    summary: DateSummary
    slots: List[SlotInfo]


class SlotCheckSummary(BaseModel):
    """전체 요약"""
    total_slots: int = Field(..., description="총 슬롯 수")
    available_dates: List[str] = Field(default_factory=list, description="예약 가능한 날짜 목록")
    total_available_slots: int = Field(..., description="예약 가능한 슬롯 수")


class SlotCheckResponse(BaseModel):
    """슬롯 조회 응답"""
    business: SlotCheckBusinessInfo
    biz_item: SlotCheckBizItemInfo
    summary: SlotCheckSummary
    slots_by_date: List[DateSlots]
    queried_at: datetime = Field(default_factory=datetime.now, description="조회 시각")
