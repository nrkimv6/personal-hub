"""
Schedule Adapter - 새 계층 구조와 기존 워커 로직 간의 어댑터
설계 문서: 2025-12-01_monitoring_restructure_design.md

이 어댑터는 새로운 계층 구조(businesses → biz_items → monitor_schedules)의 데이터를
기존 워커 로직이 기대하는 형식으로 변환합니다.

기존 워커는 MonitorTarget 객체를 기대하므로, schedule_context를 target-like 객체로 변환합니다.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from app.utils.url_builder import build_monitoring_url, get_effective_booking_options


@dataclass
class ScheduleAsTarget:
    """
    새 계층 구조의 schedule을 기존 target처럼 보이게 하는 어댑터 클래스

    기존 워커 코드에서 target.url, target.id, target.label 등을 사용하므로
    이 클래스를 통해 호환성을 유지합니다.
    """
    # 기본 식별자
    id: int  # schedule_id
    schedule_id: int  # 명시적 schedule_id

    # 기존 target 호환 필드
    url: str  # 동적 생성된 URL
    base_url: str
    label: str  # "{business_name} - {item_name} ({date})"
    date: str
    times: Optional[List[str]]

    # 상태 필드
    is_active: bool
    is_enabled: bool
    run_status: str
    last_error: Optional[str]
    error_count: int

    # 스케줄링
    interval: Optional[float]
    custom_interval: bool

    # 예약 관련
    auto_booking_enabled: bool
    max_bookings: int  # max_bookings_per_schedule
    booking_count: int
    time_range: Optional[str]
    last_booking_time: Optional[datetime]
    booking_options: Optional[Dict[str, Any]]

    # 서비스/카테고리
    service_type: str
    category: Optional[str]

    # 계층 구조 정보 (추가)
    business_pk: int
    business_id: str
    business_type_id: Optional[int]
    business_name: str
    biz_item_pk: int
    biz_item_id: str
    item_name: str

    # 타임스탬프
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def dict(self) -> Dict[str, Any]:
        """딕셔너리 변환 (기존 코드 호환)"""
        return {
            "id": self.id,
            "schedule_id": self.schedule_id,
            "url": self.url,
            "base_url": self.base_url,
            "label": self.label,
            "date": self.date,
            "times": self.times,
            "is_active": self.is_active,
            "is_enabled": self.is_enabled,
            "run_status": self.run_status,
            "last_error": self.last_error,
            "error_count": self.error_count,
            "interval": self.interval,
            "custom_interval": self.custom_interval,
            "auto_booking_enabled": self.auto_booking_enabled,
            "max_bookings": self.max_bookings,
            "booking_count": self.booking_count,
            "time_range": self.time_range,
            "last_booking_time": self.last_booking_time,
            "booking_options": self.booking_options,
            "service_type": self.service_type,
            "category": self.category,
            "business_pk": self.business_pk,
            "business_id": self.business_id,
            "business_type_id": self.business_type_id,
            "business_name": self.business_name,
            "biz_item_pk": self.biz_item_pk,
            "biz_item_id": self.biz_item_id,
            "item_name": self.item_name,
        }


def schedule_context_to_target(context: Dict[str, Any]) -> ScheduleAsTarget:
    """
    schedule_service.get_enabled_with_context() 결과를
    ScheduleAsTarget으로 변환

    Args:
        context: get_enabled_with_context()에서 반환된 단일 schedule 정보

    Returns:
        기존 target처럼 사용 가능한 ScheduleAsTarget 객체
    """
    # URL 동적 생성
    url = build_monitoring_url(context)

    # 예약 옵션 병합
    booking_options = get_effective_booking_options(context)

    # 라벨 생성
    label = f"{context['business_name']} - {context['item_name']} ({context['date']})"

    return ScheduleAsTarget(
        id=context["id"],
        schedule_id=context["id"],
        url=url,
        base_url=context.get("base_url", ""),
        label=label,
        date=context["date"],
        times=context.get("times"),
        is_active=context.get("is_active", False),
        is_enabled=context.get("is_enabled", True),
        run_status=context.get("run_status", "idle"),
        last_error=context.get("last_error"),
        error_count=context.get("error_count", 0),
        interval=context.get("interval"),
        custom_interval=context.get("custom_interval", False),
        auto_booking_enabled=context.get("auto_booking_enabled", False),
        max_bookings=context.get("max_bookings_per_schedule", 1),
        booking_count=context.get("booking_count", 0),
        time_range=context.get("time_range"),
        last_booking_time=context.get("last_booking_time"),
        booking_options=booking_options,
        service_type=context.get("service_type", "naver"),
        category=context.get("category"),
        business_pk=context["business_pk"],
        business_id=context["business_id"],
        business_type_id=context.get("business_type_id"),
        business_name=context["business_name"],
        biz_item_pk=context["biz_item_pk"],
        biz_item_id=context["biz_item_id"],
        item_name=context["item_name"],
    )


def get_enabled_schedules_as_targets(db) -> List[ScheduleAsTarget]:
    """
    활성화된 모든 schedule을 target 형식으로 조회

    Args:
        db: SQLAlchemy Session

    Returns:
        ScheduleAsTarget 객체 리스트
    """
    from app.services.schedule_service import schedule_service

    contexts = schedule_service.get_enabled_with_context(db)

    return [schedule_context_to_target(ctx) for ctx in contexts]
