"""
모니터링 이벤트 API 라우트
모니터링 체크 내역 조회 및 통계
"""
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.models.monitoring_event import MonitoringEvent
from app.models.monitor_schedule import MonitorSchedule
from app.models.biz_item import BizItem
from app.models.business import Business
from app.schemas.monitoring_event import (
    MonitoringEvent as MonitoringEventSchema,
    MonitoringEventList,
    MonitoringEventStats,
)

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


@router.get("/events", response_model=MonitoringEventList)
def get_monitoring_events(
    schedule_id: Optional[int] = Query(None, description="스케줄 ID로 필터링"),
    biz_item_id: Optional[int] = Query(None, description="상품 ID로 필터링"),
    business_id: Optional[int] = Query(None, description="업체 ID로 필터링"),
    status: Optional[str] = Query(None, description="상태로 필터링 (success/available/no_slots/hidden/paused/closed/not_opened/error)"),
    event_type: Optional[str] = Query(None, description="이벤트 타입으로 필터링"),
    date_from: Optional[str] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=200, description="페이지 크기"),
    db: Session = Depends(get_db)
):
    """
    모니터링 이벤트 목록을 조회합니다.

    - 스케줄, 상품, 업체별 필터링 지원
    - 상태 및 날짜 범위 필터링 지원
    - 페이지네이션 지원
    """
    # 기본 쿼리
    query = db.query(MonitoringEvent).join(
        MonitorSchedule, MonitoringEvent.schedule_id == MonitorSchedule.id
    ).join(
        BizItem, MonitorSchedule.biz_item_id == BizItem.id
    ).join(
        Business, BizItem.business_id == Business.id
    )

    # 필터 적용
    if schedule_id:
        query = query.filter(MonitoringEvent.schedule_id == schedule_id)

    if biz_item_id:
        query = query.filter(MonitorSchedule.biz_item_id == biz_item_id)

    if business_id:
        query = query.filter(BizItem.business_id == business_id)

    if status:
        query = query.filter(MonitoringEvent.status == status)

    if event_type:
        query = query.filter(MonitoringEvent.event_type == event_type)

    if date_from:
        try:
            from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(MonitoringEvent.timestamp >= from_dt)
        except ValueError:
            pass

    if date_to:
        try:
            to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(MonitoringEvent.timestamp < to_dt)
        except ValueError:
            pass

    # 총 개수
    total = query.count()

    # 페이지네이션
    offset = (page - 1) * page_size
    events = query.order_by(desc(MonitoringEvent.timestamp)).offset(offset).limit(page_size).all()

    # 컨텍스트 정보 추가
    result = []
    for event in events:
        schedule = db.query(MonitorSchedule).filter(MonitorSchedule.id == event.schedule_id).first()
        biz_item = None
        business = None
        if schedule:
            biz_item = db.query(BizItem).filter(BizItem.id == schedule.biz_item_id).first()
            if biz_item:
                business = db.query(Business).filter(Business.id == biz_item.business_id).first()

        event_dict = {
            "id": event.id,
            "schedule_id": event.schedule_id,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "status": event.status,
            "available_count": event.available_count,
            "slots_info": event.slots_info,
            "error_message": event.error_message,
            "response_time_ms": event.response_time_ms,
            "data_hash": event.data_hash,
            "hash_changed": event.hash_changed,
            "schedule_date": schedule.date if schedule else None,
            "biz_item_name": biz_item.name if biz_item else None,
            "business_name": business.name if business else None,
            "naver_business_id": business.business_id if business else None,
            "naver_biz_item_id": biz_item.biz_item_id if biz_item else None,
            # 상세 정보 (2025-12-08 추가)
            "fetch_method": event.fetch_method,
            "time_range": event.time_range,
            "original_slot_count": event.original_slot_count,
            "filtered_slot_count": event.filtered_slot_count,
            "target_time_matched": event.target_time_matched,
            "booking_triggered": event.booking_triggered,
            "booking_success": event.booking_success,
            # 프록시 정보 (2025-12-11 추가)
            "proxy_url": event.proxy_url,
        }
        result.append(MonitoringEventSchema(**event_dict))

    total_pages = (total + page_size - 1) // page_size

    return MonitoringEventList(
        items=result,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/events/stats", response_model=MonitoringEventStats)
def get_monitoring_stats(
    schedule_id: Optional[int] = Query(None, description="스케줄 ID로 필터링"),
    biz_item_id: Optional[int] = Query(None, description="상품 ID로 필터링"),
    business_id: Optional[int] = Query(None, description="업체 ID로 필터링"),
    date_from: Optional[str] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """
    모니터링 이벤트 통계를 조회합니다.
    """
    # 기본 쿼리
    query = db.query(MonitoringEvent)

    if schedule_id or biz_item_id or business_id:
        query = query.join(
            MonitorSchedule, MonitoringEvent.schedule_id == MonitorSchedule.id
        )

        if biz_item_id or business_id:
            query = query.join(
                BizItem, MonitorSchedule.biz_item_id == BizItem.id
            )

        if schedule_id:
            query = query.filter(MonitoringEvent.schedule_id == schedule_id)

        if biz_item_id:
            query = query.filter(MonitorSchedule.biz_item_id == biz_item_id)

        if business_id:
            query = query.filter(BizItem.business_id == business_id)

    if date_from:
        try:
            from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(MonitoringEvent.timestamp >= from_dt)
        except ValueError:
            pass

    if date_to:
        try:
            to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(MonitoringEvent.timestamp < to_dt)
        except ValueError:
            pass

    # 통계 계산
    total_checks = query.count()
    success_count = query.filter(MonitoringEvent.status == "success").count()
    available_count = query.filter(MonitoringEvent.status == "available").count()
    no_slots_count = query.filter(MonitoringEvent.status == "no_slots").count()
    hidden_count = query.filter(MonitoringEvent.status == "hidden").count()
    paused_count = query.filter(MonitoringEvent.status == "paused").count()
    closed_count = query.filter(MonitoringEvent.status == "closed").count()
    not_opened_count = query.filter(MonitoringEvent.status == "not_opened").count()
    # 비활성화: http_check_failed (HTTP 체크 실패) + http_302 (302 리다이렉트 감지)
    inactive_count = query.filter(
        MonitoringEvent.status.in_(["http_check_failed", "http_302"])
    ).count()
    error_count = query.filter(MonitoringEvent.status == "error").count()

    # 평균 응답 시간
    avg_result = query.with_entities(func.avg(MonitoringEvent.response_time_ms)).scalar()

    # 마지막 체크 시간
    last_event = query.order_by(desc(MonitoringEvent.timestamp)).first()
    last_check_time = last_event.timestamp if last_event else None

    return MonitoringEventStats(
        total_checks=total_checks,
        success_count=success_count,
        available_count=available_count,
        no_slots_count=no_slots_count,
        hidden_count=hidden_count,
        paused_count=paused_count,
        closed_count=closed_count,
        not_opened_count=not_opened_count,
        inactive_count=inactive_count,
        error_count=error_count,
        avg_response_time_ms=float(avg_result) if avg_result else None,
        last_check_time=last_check_time
    )


@router.get("/events/{event_id}", response_model=MonitoringEventSchema)
def get_monitoring_event(event_id: int, db: Session = Depends(get_db)):
    """
    모니터링 이벤트 상세 조회
    """
    event = db.query(MonitoringEvent).filter(MonitoringEvent.id == event_id).first()
    if not event:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Event not found")

    schedule = db.query(MonitorSchedule).filter(MonitorSchedule.id == event.schedule_id).first()
    biz_item = None
    business = None
    if schedule:
        biz_item = db.query(BizItem).filter(BizItem.id == schedule.biz_item_id).first()
        if biz_item:
            business = db.query(Business).filter(Business.id == biz_item.business_id).first()

    return MonitoringEventSchema(
        id=event.id,
        schedule_id=event.schedule_id,
        timestamp=event.timestamp,
        event_type=event.event_type,
        status=event.status,
        available_count=event.available_count,
        slots_info=event.slots_info,
        error_message=event.error_message,
        response_time_ms=event.response_time_ms,
        data_hash=event.data_hash,
        hash_changed=event.hash_changed,
        schedule_date=schedule.date if schedule else None,
        biz_item_name=biz_item.name if biz_item else None,
        business_name=business.name if business else None,
        naver_business_id=business.business_id if business else None,
        naver_biz_item_id=biz_item.biz_item_id if biz_item else None,
        # 상세 정보
        fetch_method=event.fetch_method,
        time_range=event.time_range,
        original_slot_count=event.original_slot_count,
        filtered_slot_count=event.filtered_slot_count,
        target_time_matched=event.target_time_matched,
        booking_triggered=event.booking_triggered,
        booking_success=event.booking_success,
        # 프록시 정보
        proxy_url=event.proxy_url,
    )


@router.delete("/events", status_code=204)
def delete_old_events(
    days: int = Query(30, ge=1, le=365, description="보관 기간 (일)"),
    db: Session = Depends(get_db)
):
    """
    지정된 기간보다 오래된 이벤트를 삭제합니다.
    """
    cutoff = datetime.now() - timedelta(days=days)
    deleted = db.query(MonitoringEvent).filter(MonitoringEvent.timestamp < cutoff).delete()
    db.commit()
    return None
