"""
MonitoringEvent 스키마 (Pydantic)
"""
import json
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional, List, Any


class MonitoringEventBase(BaseModel):
    """MonitoringEvent 기본 스키마"""
    event_type: str  # check, slot_detected, slot_booked, error
    status: str  # success, available, no_slots, error
    available_count: int = 0
    slots_info: Optional[List[Any]] = None
    error_message: Optional[str] = None
    response_time_ms: Optional[float] = None
    data_hash: Optional[str] = None
    hash_changed: bool = False


class MonitoringEventCreate(MonitoringEventBase):
    """MonitoringEvent 생성 스키마"""
    schedule_id: int


class MonitoringEvent(MonitoringEventBase):
    """MonitoringEvent 응답 스키마"""
    id: int
    schedule_id: int
    timestamp: datetime

    # 추가 컨텍스트 정보 (조회 시 포함)
    schedule_date: Optional[str] = None
    biz_item_name: Optional[str] = None
    business_name: Optional[str] = None

    @field_validator('slots_info', mode='before')
    @classmethod
    def parse_slots_info(cls, v):
        """JSON 문자열을 리스트로 변환"""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    class Config:
        from_attributes = True


class MonitoringEventList(BaseModel):
    """MonitoringEvent 목록 응답"""
    items: List[MonitoringEvent]
    total: int
    page: int
    page_size: int
    total_pages: int


class MonitoringEventStats(BaseModel):
    """모니터링 이벤트 통계"""
    total_checks: int = 0
    success_count: int = 0
    available_count: int = 0
    no_slots_count: int = 0
    error_count: int = 0
    avg_response_time_ms: Optional[float] = None
    last_check_time: Optional[datetime] = None
