"""
MonitoringEvent 스키마 (Pydantic)
"""
import json
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional, List, Any, Literal


class MonitoringEventBase(BaseModel):
    """MonitoringEvent 기본 스키마"""
    event_type: str  # check, slot_detected, slot_booked, error
    status: str  # success, available, no_slots, hidden, paused, closed, not_opened, error
    available_count: int = 0
    slots_info: Optional[List[Any]] = None
    error_message: Optional[str] = None
    response_time_ms: Optional[float] = None
    data_hash: Optional[str] = None
    hash_changed: bool = False
    # 상세 정보 (2025-12-08 추가)
    fetch_method: Optional[str] = None  # graphql_api, html_scrape, anonymous_api
    time_range: Optional[str] = None  # 적용된 시간 필터 (예: "10:00-21:00")
    original_slot_count: Optional[int] = None  # 필터링 전 전체 슬롯 개수
    filtered_slot_count: Optional[int] = None  # 필터링 후 슬롯 개수
    target_time_matched: bool = False  # time_range 내 슬롯 존재 여부
    booking_triggered: bool = False  # 자동 예약 트리거 여부
    booking_success: Optional[bool] = None  # 예약 성공 여부 (None: 미시도)
    # 프록시 정보 (2025-12-11 추가)
    proxy_url: Optional[str] = None  # 사용한 프록시 URL (익명 모니터링 시)
    # GraphQL 원본 응답 (2025-12-16 추가)
    graphql_response: Optional[Any] = None  # GraphQL API 원본 응답 데이터
    # 타이밍 상세 (2025-12-16 추가)
    graphql_time_ms: Optional[float] = None  # GraphQL 호출 시간 (ms)
    proxy_retry_count: Optional[int] = None  # 프록시 재시도 횟수
    booking_time_ms: Optional[float] = None  # 예약 실행 시간 (ms)
    booking_attempt_count: Optional[int] = None  # 예약 시도 슬롯 수


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
    # URL 생성용 ID (네이버 예약)
    naver_business_id: Optional[str] = None
    naver_biz_item_id: Optional[str] = None

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

    @field_validator('graphql_response', mode='before')
    @classmethod
    def parse_graphql_response(cls, v):
        """JSON 문자열을 딕셔너리로 변환"""
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


class CoupangPublicHistoryItem(BaseModel):
    """쿠팡 공개 페어 레코드 개별 항목"""
    id: str
    schedule_id: int
    timestamp: datetime
    opened_at: datetime
    closed_at: Optional[datetime] = None
    status_label: Literal["다시 매진", "현재 열림"]
    closed_duration_seconds: Optional[float] = None
    open_duration_seconds: Optional[float] = None
    schedule_date: Optional[str] = None
    biz_item_name: Optional[str] = None
    business_name: Optional[str] = None
    slot_key: str
    option_label: str
    slot_time_label: Optional[str] = None


class CoupangPublicHistorySummary(BaseModel):
    """쿠팡 공개 페어 이력 요약"""
    total: int = 0  # 공개 이력 레코드 수
    closed_pair_count: int = 0
    open_pair_count: int = 0
    avg_closed_duration_seconds: Optional[float] = None


class CoupangPublicHistoryResponse(BaseModel):
    """쿠팡 공개 병합 이력 응답"""
    items: List[CoupangPublicHistoryItem]
    summary: CoupangPublicHistorySummary
    slot_time_options: List[str] = Field(default_factory=list)
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
    hidden_count: int = 0  # 아이템 숨김
    paused_count: int = 0  # 예약 일시중지
    closed_count: int = 0  # 업체 비공개/운영중지
    not_opened_count: int = 0  # 예약 미오픈
    inactive_count: int = 0  # 비활성화 (http_check_failed + http_302)
    error_count: int = 0
    avg_response_time_ms: Optional[float] = None
    last_check_time: Optional[datetime] = None


# ── 취소표 통계 스키마 ────────────────────────────────────────────────────────

class CancellationStatItem(BaseModel):
    """취소표 통계 개별 항목 (일별 또는 시간대별)"""
    date: Optional[str] = None          # group_by=day: YYYY-MM-DD
    hour: Optional[int] = None          # group_by=hour: 0~23
    count: int
    biz_item_id: Optional[int] = None
    biz_item_name: Optional[str] = None


class CancellationStatsSummary(BaseModel):
    """취소표 통계 요약"""
    total: int = 0
    avg_per_day: float = 0.0
    peak_hour: Optional[int] = None     # 가장 많이 발생한 시간(시)


class CancellationStatsResponse(BaseModel):
    """취소표 시계열 통계 응답"""
    items: List[CancellationStatItem]
    summary: CancellationStatsSummary


class CancellationByProductItem(BaseModel):
    """상품별 취소표 요약 항목"""
    biz_item_id: int
    biz_item_name: str
    business_name: str
    total_count: int
    last_detected: Optional[datetime] = None
    avg_interval_hours: Optional[float] = None


class CancellationByProductResponse(BaseModel):
    """상품별 취소표 요약 응답"""
    items: List[CancellationByProductItem]
