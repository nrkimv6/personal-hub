"""
모니터링 이벤트 API 라우트
모니터링 체크 내역 조회 및 통계
"""
from typing import Optional, List
from datetime import datetime, timedelta, date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, case, extract

from app.database import get_db
from app.models.monitoring_event import MonitoringEvent
from app.models.monitoring_event_archive import MonitoringEventArchive
from app.models.monitor_schedule import MonitorSchedule
from app.models.biz_item import BizItem
from app.models.business import Business
from app.schemas.monitoring_event import (
    MonitoringEvent as MonitoringEventSchema,
    MonitoringEventList,
    MonitoringEventStats,
    CancellationStatItem,
    CancellationStatsSummary,
    CancellationStatsResponse,
    CancellationByProductItem,
    CancellationByProductResponse,
)

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


@router.get("/events", response_model=MonitoringEventList)
def get_monitoring_events(
    schedule_id: Optional[int] = Query(None, description="스케줄 ID로 필터링"),
    biz_item_id: Optional[int] = Query(None, description="상품 ID로 필터링"),
    business_id: Optional[int] = Query(None, description="업체 ID로 필터링"),
    service_type: Optional[str] = Query(None, description="서비스 타입으로 필터링 (naver/coupang/instagram)"),
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
    # 기본 쿼리 - joinedload로 N+1 쿼리 방지
    query = db.query(MonitoringEvent).options(
        joinedload(MonitoringEvent.schedule)
        .joinedload(MonitorSchedule.biz_item)
        .joinedload(BizItem.business)
    ).join(
        MonitorSchedule, MonitoringEvent.schedule_id == MonitorSchedule.id
    ).join(
        BizItem, MonitorSchedule.biz_item_id == BizItem.id
    ).join(
        Business, BizItem.business_id == Business.id
    )

    # 필터 적용
    if schedule_id is not None:
        query = query.filter(MonitoringEvent.schedule_id == schedule_id)

    if biz_item_id is not None:
        query = query.filter(MonitorSchedule.biz_item_id == biz_item_id)

    if business_id is not None:
        query = query.filter(BizItem.business_id == business_id)

    if service_type:
        query = query.filter(Business.service_type == service_type)

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

    # 컨텍스트 정보 추가 - 이미 joinedload로 로드된 관계 사용 (N+1 쿼리 방지)
    result = []
    for event in events:
        schedule = event.schedule
        biz_item = schedule.biz_item if schedule else None
        business = biz_item.business if biz_item else None

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
            # GraphQL 원본 응답 (2025-12-16 추가)
            "graphql_response": event.graphql_response,
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


@router.get("/events/archive", response_model=MonitoringEventList)
def get_monitoring_events_archive(
    schedule_id: Optional[int] = Query(None, description="스케줄 ID로 필터링"),
    status: Optional[str] = Query(None, description="상태로 필터링"),
    event_type: Optional[str] = Query(None, description="이벤트 타입으로 필터링"),
    date_from: Optional[str] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=200, description="페이지 크기"),
    db: Session = Depends(get_db),
):
    """아카이브된 모니터링 이벤트 목록 조회.

    monitoring_events_archive 파티션 테이블에서 과거 이벤트를 조회합니다.
    schedule JOIN 없음 — biz_item_id/business_id 필터 미지원.
    """
    query = db.query(MonitoringEventArchive)

    if schedule_id is not None:
        query = query.filter(MonitoringEventArchive.schedule_id == schedule_id)

    if status:
        query = query.filter(MonitoringEventArchive.status == status)

    if event_type:
        query = query.filter(MonitoringEventArchive.event_type == event_type)

    if date_from:
        try:
            from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(MonitoringEventArchive.timestamp >= from_dt)
        except ValueError:
            pass

    if date_to:
        try:
            to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(MonitoringEventArchive.timestamp < to_dt)
        except ValueError:
            pass

    total = query.count()
    offset = (page - 1) * page_size
    events = query.order_by(desc(MonitoringEventArchive.timestamp)).offset(offset).limit(page_size).all()

    result = []
    for event in events:
        event_dict = {
            "id": event.id,
            "schedule_id": event.schedule_id,
            "timestamp": event.timestamp,
            "event_type": event.event_type or "check",
            "status": event.status or "success",
            "available_count": event.available_count or 0,
            "slots_info": event.slots_info,
            "error_message": event.error_message,
            "response_time_ms": event.response_time_ms,
            "data_hash": event.data_hash,
            "hash_changed": event.hash_changed or False,
            "schedule_date": None,
            "biz_item_name": None,
            "business_name": None,
            "naver_business_id": None,
            "naver_biz_item_id": None,
            "fetch_method": event.fetch_method,
            "time_range": event.time_range,
            "original_slot_count": event.original_slot_count,
            "filtered_slot_count": event.filtered_slot_count,
            "target_time_matched": event.target_time_matched or False,
            "booking_triggered": event.booking_triggered or False,
            "booking_success": event.booking_success,
            "proxy_url": event.proxy_url,
            "graphql_response": event.graphql_response,
        }
        result.append(MonitoringEventSchema(**event_dict))

    total_pages = (total + page_size - 1) // page_size
    return MonitoringEventList(
        items=result,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/events/stats", response_model=MonitoringEventStats)
def get_monitoring_stats(
    schedule_id: Optional[int] = Query(None, description="스케줄 ID로 필터링"),
    biz_item_id: Optional[int] = Query(None, description="상품 ID로 필터링"),
    business_id: Optional[int] = Query(None, description="업체 ID로 필터링"),
    service_type: Optional[str] = Query(None, description="서비스 타입으로 필터링 (naver/coupang/instagram)"),
    date_from: Optional[str] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """
    모니터링 이벤트 통계를 조회합니다.
    단일 쿼리로 모든 상태별 카운트를 집계합니다. (성능 최적화)
    """
    # 기본 쿼리
    query = db.query(MonitoringEvent)

    join_schedule = (
        schedule_id is not None
        or biz_item_id is not None
        or business_id is not None
        or service_type is not None
    )
    join_biz_item = (
        biz_item_id is not None
        or business_id is not None
        or service_type is not None
    )
    join_business = (
        business_id is not None
        or service_type is not None
    )

    if join_schedule:
        query = query.join(
            MonitorSchedule, MonitoringEvent.schedule_id == MonitorSchedule.id
        )

        if join_biz_item:
            query = query.join(
                BizItem, MonitorSchedule.biz_item_id == BizItem.id
            )

        if join_business:
            query = query.join(
                Business, BizItem.business_id == Business.id
            )

        if schedule_id is not None:
            query = query.filter(MonitoringEvent.schedule_id == schedule_id)

        if biz_item_id is not None:
            query = query.filter(MonitorSchedule.biz_item_id == biz_item_id)

        if business_id is not None:
            query = query.filter(BizItem.business_id == business_id)

        if service_type is not None:
            query = query.filter(Business.service_type == service_type)

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

    # 통계 계산 - 단일 쿼리로 모든 카운트 집계 (10개 쿼리 -> 1개로 최적화)
    stats = query.with_entities(
        func.count(MonitoringEvent.id).label('total'),
        func.sum(case((MonitoringEvent.status == 'success', 1), else_=0)).label('success'),
        func.sum(case((MonitoringEvent.status == 'available', 1), else_=0)).label('available'),
        func.sum(case((MonitoringEvent.status == 'no_slots', 1), else_=0)).label('no_slots'),
        func.sum(case((MonitoringEvent.status == 'hidden', 1), else_=0)).label('hidden'),
        func.sum(case((MonitoringEvent.status == 'paused', 1), else_=0)).label('paused'),
        func.sum(case((MonitoringEvent.status == 'closed', 1), else_=0)).label('closed'),
        func.sum(case((MonitoringEvent.status == 'not_opened', 1), else_=0)).label('not_opened'),
        func.sum(case((MonitoringEvent.status.in_(['inactive', 'http_302', 'inactive_blocked']), 1), else_=0)).label('inactive'),
        func.sum(case((MonitoringEvent.status == 'error', 1), else_=0)).label('error'),
        func.avg(MonitoringEvent.response_time_ms).label('avg_response_time'),
        func.max(MonitoringEvent.timestamp).label('last_check')
    ).first()

    return MonitoringEventStats(
        total_checks=stats.total or 0,
        success_count=int(stats.success or 0),
        available_count=int(stats.available or 0),
        no_slots_count=int(stats.no_slots or 0),
        hidden_count=int(stats.hidden or 0),
        paused_count=int(stats.paused or 0),
        closed_count=int(stats.closed or 0),
        not_opened_count=int(stats.not_opened or 0),
        inactive_count=int(stats.inactive or 0),
        error_count=int(stats.error or 0),
        avg_response_time_ms=float(stats.avg_response_time) if stats.avg_response_time else None,
        last_check_time=stats.last_check
    )


@router.get("/events/cancellation-stats", response_model=CancellationStatsResponse)
def get_cancellation_stats(
    date_from: Optional[str] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    biz_item_id: Optional[int] = Query(None, description="상품 ID 필터"),
    hours: Optional[str] = Query(None, description="시간 필터 — 쉼표 구분 정수 (예: 13,15,18), 시간끼리 OR"),
    group_by: str = Query("day", description="집계 기준: day | hour"),
    db: Session = Depends(get_db),
):
    """
    쿠팡 취소표(status=available) 시계열 통계 조회.

    - group_by=day: 일별 발생 횟수
    - group_by=hour: 시간대별 발생 횟수
    - hours: 특정 시간대만 필터 (날짜 AND 시간, 시간끼리 OR)
    """
    # 기본 쿼리 — 쿠팡 서비스의 available(취소표 감지) 이벤트만
    query = (
        db.query(MonitoringEvent)
        .join(MonitorSchedule, MonitoringEvent.schedule_id == MonitorSchedule.id)
        .join(BizItem, MonitorSchedule.biz_item_id == BizItem.id)
        .join(Business, BizItem.business_id == Business.id)
        .filter(Business.service_type == "coupang")
        .filter(MonitoringEvent.status == "available")
    )

    if biz_item_id is not None:
        query = query.filter(MonitorSchedule.biz_item_id == biz_item_id)

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

    # 시간 필터 (시간끼리 OR)
    hour_list: List[int] = []
    if hours:
        for h in hours.split(","):
            h = h.strip()
            if h.isdigit() and 0 <= int(h) <= 23:
                hour_list.append(int(h))
    if hour_list:
        query = query.filter(extract("hour", MonitoringEvent.timestamp).in_(hour_list))

    # 집계
    if group_by == "hour":
        rows = (
            query.with_entities(
                extract("hour", MonitoringEvent.timestamp).label("hour"),
                BizItem.id.label("biz_item_id"),
                BizItem.name.label("biz_item_name"),
                func.count(MonitoringEvent.id).label("count"),
            )
            .group_by(
                extract("hour", MonitoringEvent.timestamp),
                BizItem.id,
                BizItem.name,
            )
            .order_by(extract("hour", MonitoringEvent.timestamp))
            .all()
        )
        items = [
            CancellationStatItem(
                hour=int(r.hour),
                biz_item_id=r.biz_item_id,
                biz_item_name=r.biz_item_name,
                count=r.count,
            )
            for r in rows
        ]
    else:
        # group_by=day (default)
        rows = (
            query.with_entities(
                func.date_trunc("day", MonitoringEvent.timestamp).label("day"),
                BizItem.id.label("biz_item_id"),
                BizItem.name.label("biz_item_name"),
                func.count(MonitoringEvent.id).label("count"),
            )
            .group_by(
                func.date_trunc("day", MonitoringEvent.timestamp),
                BizItem.id,
                BizItem.name,
            )
            .order_by(func.date_trunc("day", MonitoringEvent.timestamp))
            .all()
        )
        items = [
            CancellationStatItem(
                date=r.day.strftime("%Y-%m-%d") if r.day else None,
                biz_item_id=r.biz_item_id,
                biz_item_name=r.biz_item_name,
                count=r.count,
            )
            for r in rows
        ]

    # summary 계산
    total = sum(i.count for i in items)

    # avg_per_day: 날짜 범위 기반
    try:
        if date_from and date_to:
            d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
            d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
            day_count = max((d_to - d_from).days + 1, 1)
        elif items and group_by == "day":
            day_count = len({i.date for i in items if i.date})
            day_count = max(day_count, 1)
        else:
            day_count = 1
    except Exception:
        day_count = 1

    avg_per_day = round(total / day_count, 2) if day_count > 0 else 0.0

    # peak_hour: 시간대별 합산에서 최고값
    hour_counts: dict = {}
    for i in items:
        if i.hour is not None:
            hour_counts[i.hour] = hour_counts.get(i.hour, 0) + i.count
    peak_hour = max(hour_counts, key=lambda h: hour_counts[h]) if hour_counts else None

    summary = CancellationStatsSummary(total=total, avg_per_day=avg_per_day, peak_hour=peak_hour)
    return CancellationStatsResponse(items=items, summary=summary)


@router.get("/events/cancellation-by-product", response_model=CancellationByProductResponse)
def get_cancellation_by_product(
    date_from: Optional[str] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    hours: Optional[str] = Query(None, description="시간 필터 — 쉼표 구분 정수 (예: 13,15,18), 시간끼리 OR"),
    db: Session = Depends(get_db),
):
    """
    쿠팡 취소표 상품별 발생 횟수 랭킹 (count desc 정렬).
    """
    query = (
        db.query(MonitoringEvent)
        .join(MonitorSchedule, MonitoringEvent.schedule_id == MonitorSchedule.id)
        .join(BizItem, MonitorSchedule.biz_item_id == BizItem.id)
        .join(Business, BizItem.business_id == Business.id)
        .filter(Business.service_type == "coupang")
        .filter(MonitoringEvent.status == "available")
    )

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

    hour_list: List[int] = []
    if hours:
        for h in hours.split(","):
            h = h.strip()
            if h.isdigit() and 0 <= int(h) <= 23:
                hour_list.append(int(h))
    if hour_list:
        query = query.filter(extract("hour", MonitoringEvent.timestamp).in_(hour_list))

    rows = (
        query.with_entities(
            BizItem.id.label("biz_item_id"),
            BizItem.name.label("biz_item_name"),
            Business.name.label("business_name"),
            func.count(MonitoringEvent.id).label("total_count"),
            func.max(MonitoringEvent.timestamp).label("last_detected"),
        )
        .group_by(BizItem.id, BizItem.name, Business.name)
        .order_by(desc(func.count(MonitoringEvent.id)))
        .all()
    )

    items = []
    for r in rows:
        # avg_interval_hours: 해당 상품의 이벤트 간 평균 간격 (Python 후처리)
        avg_interval = None
        if r.total_count >= 2:
            timestamps = (
                db.query(MonitoringEvent.timestamp)
                .join(MonitorSchedule, MonitoringEvent.schedule_id == MonitorSchedule.id)
                .join(BizItem, MonitorSchedule.biz_item_id == BizItem.id)
                .filter(BizItem.id == r.biz_item_id)
                .filter(MonitoringEvent.status == "available")
                .order_by(MonitoringEvent.timestamp)
                .all()
            )
            ts_list = [t[0] for t in timestamps if t[0]]
            if len(ts_list) >= 2:
                intervals = [
                    (ts_list[i + 1] - ts_list[i]).total_seconds() / 3600
                    for i in range(len(ts_list) - 1)
                ]
                avg_interval = round(sum(intervals) / len(intervals), 2)

        items.append(
            CancellationByProductItem(
                biz_item_id=r.biz_item_id,
                biz_item_name=r.biz_item_name,
                business_name=r.business_name,
                total_count=r.total_count,
                last_detected=r.last_detected,
                avg_interval_hours=avg_interval,
            )
        )

    return CancellationByProductResponse(items=items)


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
        # GraphQL 원본 응답
        graphql_response=event.graphql_response,
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
