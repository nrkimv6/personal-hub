"""
MonitorSchedule 서비스 - 일정 CRUD
설계 문서: 2025-12-01_monitoring_restructure_design.md
"""
import json
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, date

from app.models.monitor_schedule import MonitorSchedule
from app.models.biz_item import BizItem
from app.models.business import Business
from app.models.monitoring_event import MonitoringEvent
from app.schemas.monitor_schedule import (
    MonitorScheduleCreate,
    MonitorScheduleUpdate,
    BulkScheduleCreate,
    ScheduleWithContext,
    coerce_monitoring_mode,
)


def calculate_default_interval(target_date_str: str) -> int:
    """
    날짜 기반 기본 모니터링 간격 계산

    Args:
        target_date_str: 목표 날짜 (YYYY-MM-DD 형식)

    Returns:
        모니터링 간격 (초)
    """
    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        today = date.today()
        days_until = (target_date - today).days

        if days_until <= 1:
            return 30      # D-1 이하: 30초
        elif days_until <= 3:
            return 60      # D-3 이하: 1분
        elif days_until <= 7:
            return 300     # D-7 이하: 5분
        else:
            return 900     # D-7 초과: 15분
    except (ValueError, TypeError):
        return 60  # 파싱 실패 시 기본값 1분


class ScheduleService:
    """일정 관리 서비스"""

    @staticmethod
    def serialize_times(times: Optional[List[str]]) -> Optional[str]:
        """times를 저장용 JSON 문자열로 직렬화한다."""
        if not times:
            return None
        normalized = sorted(str(item) for item in times)
        return json.dumps(normalized, ensure_ascii=False)

    def get_by_item(self, db: Session, biz_item_id: int) -> List[MonitorSchedule]:
        """아이템별 일정 목록 조회 (service_account 포함)"""
        return db.query(MonitorSchedule).options(
            joinedload(MonitorSchedule.service_account)
        ).filter(
            MonitorSchedule.biz_item_id == biz_item_id
        ).order_by(MonitorSchedule.date).all()

    def get_by_id(self, db: Session, schedule_id: int) -> Optional[MonitorSchedule]:
        """ID로 일정 조회 (service_account 포함)"""
        return db.query(MonitorSchedule).options(
            joinedload(MonitorSchedule.service_account)
        ).filter(MonitorSchedule.id == schedule_id).first()

    def get_all_enabled(self, db: Session) -> List[MonitorSchedule]:
        """활성화된 모든 일정 조회"""
        return db.query(MonitorSchedule).filter(
            MonitorSchedule.is_enabled == True
        ).order_by(MonitorSchedule.date).all()

    def get_all_active(self, db: Session) -> List[MonitorSchedule]:
        """현재 모니터링 중인 일정 조회"""
        return db.query(MonitorSchedule).filter(
            MonitorSchedule.is_active == True
        ).all()

    def get_all_with_context(
        self,
        db: Session,
        is_enabled: Optional[bool] = None,
        business_id: Optional[int] = None,
        biz_item_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        search: Optional[str] = None,
        service_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """전체 일정 + 상위 컨텍스트 조회 (일정 관리 페이지용)"""
        query = db.query(
            MonitorSchedule,
            BizItem,
            Business
        ).options(
            joinedload(MonitorSchedule.service_account)
        ).join(
            BizItem, MonitorSchedule.biz_item_id == BizItem.id
        ).join(
            Business, BizItem.business_id == Business.id
        )

        # 필터 적용
        if is_enabled is not None:
            query = query.filter(MonitorSchedule.is_enabled == is_enabled)
        if business_id is not None:
            query = query.filter(Business.id == business_id)
        if biz_item_id is not None:
            query = query.filter(BizItem.id == biz_item_id)
        if date_from:
            query = query.filter(MonitorSchedule.date >= date_from)
        if date_to:
            query = query.filter(MonitorSchedule.date <= date_to)
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (Business.name.ilike(search_pattern)) |
                (BizItem.name.ilike(search_pattern))
            )
        if service_type is not None:
            query = query.filter(Business.service_type == service_type)

        results = query.order_by(MonitorSchedule.date.desc()).all()
        schedule_ids = [schedule.id for schedule, item, business in results]
        last_events = self._get_last_events(db, schedule_ids)
        return self._build_context_list(results, last_events)

    def _get_last_events(self, db: Session, schedule_ids: list) -> dict:
        """schedule_id 목록에 대해 최신 monitoring_event의 timestamp와 status를 반환.

        Returns:
            {schedule_id: (last_event_at_iso_str, last_event_status)} dict
        """
        if not schedule_ids:
            return {}

        from sqlalchemy import func

        # Step 1: schedule_id별 MAX(timestamp)
        max_ts_sq = (
            db.query(
                MonitoringEvent.schedule_id,
                func.max(MonitoringEvent.timestamp).label("max_ts")
            )
            .filter(MonitoringEvent.schedule_id.in_(schedule_ids))
            .group_by(MonitoringEvent.schedule_id)
            .subquery()
        )

        # Step 2: 해당 timestamp의 status 조회
        events = (
            db.query(
                MonitoringEvent.schedule_id,
                MonitoringEvent.timestamp,
                MonitoringEvent.status
            )
            .join(
                max_ts_sq,
                (MonitoringEvent.schedule_id == max_ts_sq.c.schedule_id) &
                (MonitoringEvent.timestamp == max_ts_sq.c.max_ts)
            )
            .all()
        )

        return {
            e.schedule_id: (
                e.timestamp.isoformat() if e.timestamp else None,
                e.status
            )
            for e in events
        }

    def _build_context_list(self, results, last_events: dict = None) -> List[Dict[str, Any]]:
        """결과 목록을 컨텍스트 딕셔너리 목록으로 변환"""
        if last_events is None:
            last_events = {}
        schedules_with_context = []
        for schedule, item, business in results:
            last_event_at, last_event_status = last_events.get(schedule.id, (None, None))
            schedules_with_context.append(
                self._build_context_dict(schedule, item, business,
                                          last_event_at=last_event_at,
                                          last_event_status=last_event_status)
            )
        return schedules_with_context

    def _build_context_dict(self, schedule, item, business,
                             last_event_at=None, last_event_status=None) -> Dict[str, Any]:
        """단일 결과를 컨텍스트 딕셔너리로 변환"""
        # interval 계산: custom_interval이면 저장된 값, 아니면 날짜 기반 기본값
        if schedule.custom_interval and schedule.interval is not None:
            effective_interval = schedule.interval
        else:
            effective_interval = calculate_default_interval(schedule.date)

        return {
            # Schedule 정보
            "id": schedule.id,
            "date": schedule.date,
            "time_range": getattr(schedule, 'time_range', None) or item.time_range,  # schedule 우선, 없으면 item
            "times": json.loads(schedule.times) if schedule.times else None,
            "is_enabled": schedule.is_enabled,
            "is_active": schedule.is_active,
            "run_status": schedule.run_status,
            "last_error": schedule.last_error,
            "error_count": schedule.error_count,
            "interval": effective_interval,
            "custom_interval": schedule.custom_interval,
            "booking_count": schedule.booking_count,
            "last_booking_time": schedule.last_booking_time,
            "service_account_id": schedule.service_account_id,
            "account_name": schedule.service_account.profile.name if schedule.service_account else None,
            "auto_booking_enabled": getattr(schedule, 'auto_booking_enabled', False),
            "monitoring_mode": coerce_monitoring_mode(getattr(schedule, "monitoring_mode", None)),
            "created_at": schedule.created_at,
            "updated_at": schedule.updated_at,
            # BizItem 정보
            "biz_item_pk": item.id,
            "biz_item_id": schedule.biz_item_id,
            "item_biz_item_id": item.biz_item_id,
            "item_name": item.name,
            "base_url": item.base_url,
            "item_is_enabled": getattr(item, 'is_enabled', True),
            "item_time_range": item.time_range,  # 아이템 레벨 time_range (폴백용)
            "max_bookings_per_schedule": item.max_bookings_per_schedule,
            "booking_options_override": json.loads(item.booking_options_override) if item.booking_options_override else None,
            # Business 정보
            "business_pk": business.id,
            "business_id": business.business_id,
            "business_type_id": business.business_type_id,
            "business_name": business.name,
            "business_is_enabled": getattr(business, 'is_enabled', True),
            "service_type": business.service_type,
            "category": business.category,
            "booking_options": json.loads(business.booking_options) if business.booking_options else None,
            # 마지막 모니터링 시간
            "last_check": schedule.updated_at,
            "last_check_time": getattr(schedule, 'last_check_time', None),
            "next_run_time": getattr(schedule, 'next_run_time', None),
            # 최신 실행 흔적
            "last_event_at": last_event_at,
            "last_event_status": last_event_status,
        }

    def get_enabled_with_context(self, db: Session) -> List[Dict[str, Any]]:
        """활성화된 일정 + 상위 컨텍스트 조회 (워커용)"""
        return self.get_all_with_context(db, is_enabled=True)

    def create(self, db: Session, data: MonitorScheduleCreate) -> MonitorSchedule:
        """일정 생성"""
        times_json = self.serialize_times(data.times)

        schedule = MonitorSchedule(
            biz_item_id=data.biz_item_id,
            date=data.date,
            time_range=data.time_range,
            times=times_json,
            is_enabled=data.is_enabled,
            auto_booking_enabled=data.auto_booking_enabled,
            interval=data.interval,
            custom_interval=data.custom_interval,
            service_account_id=data.service_account_id,
            monitoring_mode=coerce_monitoring_mode(data.monitoring_mode),
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        return schedule

    def create_bulk(self, db: Session, data: BulkScheduleCreate) -> List[MonitorSchedule]:
        """일정 일괄 생성"""
        times_json = self.serialize_times(data.times)

        schedules = []
        for date in data.dates:
            schedule = MonitorSchedule(
                biz_item_id=data.biz_item_id,
                date=date,
                time_range=data.time_range,
                times=times_json,
                is_enabled=data.is_enabled,
                interval=data.interval,
                custom_interval=data.custom_interval,
                service_account_id=data.service_account_id,
                monitoring_mode=coerce_monitoring_mode(data.monitoring_mode),
            )
            db.add(schedule)
            schedules.append(schedule)

        db.commit()

        # refresh all
        for schedule in schedules:
            db.refresh(schedule)

        return schedules

    def update(self, db: Session, schedule_id: int, data: MonitorScheduleUpdate) -> Optional[MonitorSchedule]:
        """일정 수정"""
        schedule = self.get_by_id(db, schedule_id)
        if not schedule:
            return None

        update_data = data.model_dump(exclude_unset=True)

        # times JSON 변환
        if "times" in update_data and update_data["times"] is not None:
            update_data["times"] = self.serialize_times(update_data["times"])
        if "monitoring_mode" in update_data:
            update_data["monitoring_mode"] = coerce_monitoring_mode(update_data["monitoring_mode"])

        for key, value in update_data.items():
            setattr(schedule, key, value)

        schedule.updated_at = datetime.now()
        db.commit()
        db.refresh(schedule)
        return schedule

    def delete(self, db: Session, schedule_id: int) -> bool:
        """일정 삭제"""
        schedule = self.get_by_id(db, schedule_id)
        if not schedule:
            return False

        db.delete(schedule)
        db.commit()
        return True

    def enable(self, db: Session, schedule_id: int) -> Optional[MonitorSchedule]:
        """일정 활성화"""
        return self.update(db, schedule_id, MonitorScheduleUpdate(
            is_enabled=True,
            run_status="pending"
        ))

    def disable(self, db: Session, schedule_id: int) -> Optional[MonitorSchedule]:
        """일정 비활성화"""
        return self.update(db, schedule_id, MonitorScheduleUpdate(
            is_enabled=False,
            run_status="paused"
        ))

    def set_active(self, db: Session, schedule_id: int, is_active: bool) -> Optional[MonitorSchedule]:
        """시스템 활성 상태 설정 (워커용)"""
        return self.update(db, schedule_id, MonitorScheduleUpdate(
            is_active=is_active,
            run_status="running" if is_active else "idle"
        ))

    def set_last_check_time(
        self,
        db: Session,
        schedule_id: int,
        check_time: Optional[datetime] = None,
    ) -> Optional[MonitorSchedule]:
        """스케줄 마지막 확인 시각 갱신 (워커 체크 완료/시도 시점)."""
        schedule = self.get_by_id(db, schedule_id)
        if not schedule:
            return None

        schedule.last_check_time = check_time or datetime.now()
        schedule.updated_at = datetime.now()
        db.commit()
        db.refresh(schedule)
        return schedule

    def increment_booking_count(self, db: Session, schedule_id: int) -> Optional[MonitorSchedule]:
        """예약 횟수 증가"""
        schedule = self.get_by_id(db, schedule_id)
        if not schedule:
            return None

        schedule.booking_count += 1
        schedule.last_booking_time = datetime.now()
        schedule.updated_at = datetime.now()
        db.commit()
        db.refresh(schedule)
        return schedule


# 싱글톤 인스턴스
schedule_service = ScheduleService()
