"""
일별 통계 집계 서비스
작성일: 2025-12-23

proxy_usage_logs, monitoring_events 등의 상세 로그를
일별 통계로 집계하여 저장합니다.
"""
import json
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple

from sqlalchemy import func, and_, case
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.daily_stats import ProxyDailyStats, MonitoringDailyStats
from app.models.proxy_usage import ProxyUsageLog
from app.models.monitoring_event import MonitoringEvent
from app.schemas.daily_stats import (
    ProxyDailyStatsResponse,
    MonitoringDailyStatsResponse,
    ProxyDailyStatsListParams,
    MonitoringDailyStatsListParams,
)

logger = logging.getLogger(__name__)


class DailyStatsService:
    """일별 통계 집계 서비스"""

    def aggregate_proxy_daily_stats(
        self,
        db: Session,
        target_date: Optional[date] = None,
        force: bool = False,
    ) -> int:
        """
        프록시 사용 로그를 일별 통계로 집계

        Args:
            db: 데이터베이스 세션
            target_date: 집계 대상 날짜 (None이면 어제)
            force: True면 기존 집계 덮어쓰기

        Returns:
            집계된 프록시 수
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        # 이미 집계된 경우 스킵 (force가 아니면)
        if not force:
            existing = db.query(ProxyDailyStats).filter(
                ProxyDailyStats.date == target_date
            ).first()
            if existing:
                logger.info(f"Proxy daily stats already exists for {target_date}, skipping")
                return 0

        # force 모드면 기존 데이터 삭제
        if force:
            deleted = db.query(ProxyDailyStats).filter(
                ProxyDailyStats.date == target_date
            ).delete()
            if deleted:
                logger.info(f"Deleted {deleted} existing proxy daily stats for {target_date}")

        # 해당 날짜의 시작/끝 시간
        start_dt = datetime.combine(target_date, datetime.min.time())
        end_dt = datetime.combine(target_date + timedelta(days=1), datetime.min.time())

        # 프록시별 통계 집계
        stats_query = db.query(
            ProxyUsageLog.proxy_host,
            func.count(ProxyUsageLog.id).label("total_attempts"),
            func.sum(ProxyUsageLog.success).label("success_count"),
            func.sum(case((ProxyUsageLog.success == 0, 1), else_=0)).label("fail_count"),
            func.avg(
                case(
                    (ProxyUsageLog.success == 1, ProxyUsageLog.response_time_ms),
                    else_=None
                )
            ).label("avg_response_time_ms"),
            func.min(
                case(
                    (ProxyUsageLog.success == 1, ProxyUsageLog.response_time_ms),
                    else_=None
                )
            ).label("min_response_time_ms"),
            func.max(
                case(
                    (ProxyUsageLog.success == 1, ProxyUsageLog.response_time_ms),
                    else_=None
                )
            ).label("max_response_time_ms"),
        ).filter(
            ProxyUsageLog.timestamp >= start_dt,
            ProxyUsageLog.timestamp < end_dt,
            ProxyUsageLog.proxy_host.isnot(None),
        ).group_by(
            ProxyUsageLog.proxy_host
        )

        rows = stats_query.all()

        if not rows:
            logger.info(f"No proxy usage logs found for {target_date}")
            return 0

        # 프록시 호스트 목록
        proxy_hosts = [row.proxy_host for row in rows]

        # 에러 유형별 카운트 조회 (별도 쿼리)
        error_types_by_proxy = self._get_error_types_by_proxy(
            db, start_dt, end_dt, proxy_hosts
        )

        # 일별 통계 레코드 생성
        aggregated_count = 0
        for row in rows:
            error_types = error_types_by_proxy.get(row.proxy_host, {})

            stats = ProxyDailyStats(
                date=target_date,
                proxy_host=row.proxy_host,
                total_attempts=row.total_attempts or 0,
                success_count=int(row.success_count or 0),
                fail_count=int(row.fail_count or 0),
                avg_response_time_ms=row.avg_response_time_ms,
                min_response_time_ms=row.min_response_time_ms,
                max_response_time_ms=row.max_response_time_ms,
                error_types=json.dumps(error_types) if error_types else None,
            )
            db.add(stats)
            aggregated_count += 1

        db.commit()
        logger.info(f"Aggregated proxy daily stats for {target_date}: {aggregated_count} proxies")
        return aggregated_count

    def _get_error_types_by_proxy(
        self,
        db: Session,
        start_dt: datetime,
        end_dt: datetime,
        proxy_hosts: List[str],
    ) -> Dict[str, Dict[str, int]]:
        """프록시별 에러 유형 카운트 조회"""
        if not proxy_hosts:
            return {}

        error_query = db.query(
            ProxyUsageLog.proxy_host,
            ProxyUsageLog.error_type,
            func.count(ProxyUsageLog.id).label("count")
        ).filter(
            ProxyUsageLog.timestamp >= start_dt,
            ProxyUsageLog.timestamp < end_dt,
            ProxyUsageLog.proxy_host.in_(proxy_hosts),
            ProxyUsageLog.success == 0,
            ProxyUsageLog.error_type.isnot(None),
        ).group_by(
            ProxyUsageLog.proxy_host,
            ProxyUsageLog.error_type
        )

        result: Dict[str, Dict[str, int]] = {}
        for row in error_query.all():
            if row.proxy_host not in result:
                result[row.proxy_host] = {}
            result[row.proxy_host][row.error_type] = row.count

        return result

    def aggregate_monitoring_daily_stats(
        self,
        db: Session,
        target_date: Optional[date] = None,
        force: bool = False,
    ) -> int:
        """
        모니터링 이벤트를 일별 통계로 집계

        Args:
            db: 데이터베이스 세션
            target_date: 집계 대상 날짜 (None이면 어제)
            force: True면 기존 집계 덮어쓰기

        Returns:
            집계된 스케줄 수
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        # 이미 집계된 경우 스킵 (force가 아니면)
        if not force:
            existing = db.query(MonitoringDailyStats).filter(
                MonitoringDailyStats.date == target_date
            ).first()
            if existing:
                logger.info(f"Monitoring daily stats already exists for {target_date}, skipping")
                return 0

        # force 모드면 기존 데이터 삭제
        if force:
            deleted = db.query(MonitoringDailyStats).filter(
                MonitoringDailyStats.date == target_date
            ).delete()
            if deleted:
                logger.info(f"Deleted {deleted} existing monitoring daily stats for {target_date}")

        # 해당 날짜의 시작/끝 시간
        start_dt = datetime.combine(target_date, datetime.min.time())
        end_dt = datetime.combine(target_date + timedelta(days=1), datetime.min.time())

        # 스케줄별 통계 집계
        stats_query = db.query(
            MonitoringEvent.schedule_id,
            func.count(MonitoringEvent.id).label("check_count"),
            func.sum(
                case((MonitoringEvent.status == "success", 1), else_=0)
            ).label("success_count"),
            func.sum(
                case((MonitoringEvent.status == "error", 1), else_=0)
            ).label("error_count"),
            func.sum(
                case((MonitoringEvent.status == "available", 1), else_=0)
            ).label("available_detected"),
            func.sum(
                case((MonitoringEvent.booking_triggered == True, 1), else_=0)
            ).label("booking_triggered"),
            func.sum(
                case((MonitoringEvent.booking_success == True, 1), else_=0)
            ).label("booking_success"),
            func.avg(MonitoringEvent.response_time_ms).label("avg_response_time_ms"),
        ).filter(
            MonitoringEvent.timestamp >= start_dt,
            MonitoringEvent.timestamp < end_dt,
        ).group_by(
            MonitoringEvent.schedule_id
        )

        rows = stats_query.all()

        if not rows:
            logger.info(f"No monitoring events found for {target_date}")
            return 0

        # 일별 통계 레코드 생성
        aggregated_count = 0
        for row in rows:
            stats = MonitoringDailyStats(
                date=target_date,
                schedule_id=row.schedule_id,
                check_count=row.check_count or 0,
                success_count=int(row.success_count or 0),
                error_count=int(row.error_count or 0),
                available_detected=int(row.available_detected or 0),
                booking_triggered=int(row.booking_triggered or 0),
                booking_success=int(row.booking_success or 0),
                avg_response_time_ms=row.avg_response_time_ms,
            )
            db.add(stats)
            aggregated_count += 1

        db.commit()
        logger.info(f"Aggregated monitoring daily stats for {target_date}: {aggregated_count} schedules")
        return aggregated_count

    def aggregate_date_range(
        self,
        db: Session,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> Tuple[int, int]:
        """
        날짜 범위에 대해 일별 통계 집계

        Args:
            db: 데이터베이스 세션
            start_date: 시작 날짜
            end_date: 종료 날짜 (포함)
            force: True면 기존 집계 덮어쓰기

        Returns:
            (프록시 통계 수, 모니터링 통계 수) 튜플
        """
        proxy_total = 0
        monitoring_total = 0

        current = start_date
        while current <= end_date:
            proxy_count = self.aggregate_proxy_daily_stats(db, current, force)
            monitoring_count = self.aggregate_monitoring_daily_stats(db, current, force)

            proxy_total += proxy_count
            monitoring_total += monitoring_count

            logger.debug(f"Aggregated {current}: proxy={proxy_count}, monitoring={monitoring_count}")
            current += timedelta(days=1)

        return proxy_total, monitoring_total

    def get_proxy_daily_stats(
        self,
        db: Session,
        params: ProxyDailyStatsListParams,
    ) -> List[ProxyDailyStatsResponse]:
        """프록시 일별 통계 조회"""
        query = db.query(ProxyDailyStats)

        if params.date_from:
            query = query.filter(ProxyDailyStats.date >= params.date_from)
        if params.date_to:
            query = query.filter(ProxyDailyStats.date <= params.date_to)
        if params.proxy_host:
            query = query.filter(ProxyDailyStats.proxy_host == params.proxy_host)

        query = query.order_by(
            ProxyDailyStats.date.desc(),
            ProxyDailyStats.total_attempts.desc()
        ).offset(params.offset).limit(params.limit)

        stats = query.all()

        return [
            ProxyDailyStatsResponse(
                id=s.id,
                date=s.date,
                proxy_host=s.proxy_host,
                total_attempts=s.total_attempts,
                success_count=s.success_count,
                fail_count=s.fail_count,
                avg_response_time_ms=s.avg_response_time_ms,
                min_response_time_ms=s.min_response_time_ms,
                max_response_time_ms=s.max_response_time_ms,
                error_types=json.loads(s.error_types) if s.error_types else None,
                created_at=s.created_at,
            )
            for s in stats
        ]

    def get_monitoring_daily_stats(
        self,
        db: Session,
        params: MonitoringDailyStatsListParams,
    ) -> List[MonitoringDailyStatsResponse]:
        """모니터링 일별 통계 조회"""
        from app.models.monitor_schedule import MonitorSchedule
        from app.models.biz_item import BizItem
        from app.models.business import Business

        query = db.query(
            MonitoringDailyStats,
            Business.name.label("business_name"),
            BizItem.name.label("biz_item_name"),
        ).outerjoin(
            MonitorSchedule, MonitoringDailyStats.schedule_id == MonitorSchedule.id
        ).outerjoin(
            BizItem, MonitorSchedule.biz_item_id == BizItem.id
        ).outerjoin(
            Business, BizItem.business_id == Business.id
        )

        if params.date_from:
            query = query.filter(MonitoringDailyStats.date >= params.date_from)
        if params.date_to:
            query = query.filter(MonitoringDailyStats.date <= params.date_to)
        if params.schedule_id:
            query = query.filter(MonitoringDailyStats.schedule_id == params.schedule_id)

        query = query.order_by(
            MonitoringDailyStats.date.desc(),
            MonitoringDailyStats.check_count.desc()
        ).offset(params.offset).limit(params.limit)

        rows = query.all()

        return [
            MonitoringDailyStatsResponse(
                id=row.MonitoringDailyStats.id,
                date=row.MonitoringDailyStats.date,
                schedule_id=row.MonitoringDailyStats.schedule_id,
                check_count=row.MonitoringDailyStats.check_count,
                success_count=row.MonitoringDailyStats.success_count,
                error_count=row.MonitoringDailyStats.error_count,
                available_detected=row.MonitoringDailyStats.available_detected,
                booking_triggered=row.MonitoringDailyStats.booking_triggered,
                booking_success=row.MonitoringDailyStats.booking_success,
                avg_response_time_ms=row.MonitoringDailyStats.avg_response_time_ms,
                created_at=row.MonitoringDailyStats.created_at,
                business_name=row.business_name,
                biz_item_name=row.biz_item_name,
            )
            for row in rows
        ]

    def get_stats_summary(
        self,
        db: Session,
    ) -> Dict[str, Any]:
        """통계 요약 정보 조회"""
        # 프록시 일별 통계 정보
        proxy_stats_count = db.query(func.count(ProxyDailyStats.id)).scalar() or 0
        oldest_proxy_stats = db.query(func.min(ProxyDailyStats.date)).scalar()
        latest_proxy_stats = db.query(func.max(ProxyDailyStats.date)).scalar()

        # 모니터링 일별 통계 정보
        monitoring_stats_count = db.query(func.count(MonitoringDailyStats.id)).scalar() or 0
        oldest_monitoring_stats = db.query(func.min(MonitoringDailyStats.date)).scalar()
        latest_monitoring_stats = db.query(func.max(MonitoringDailyStats.date)).scalar()

        return {
            "proxy_daily_stats": {
                "count": proxy_stats_count,
                "oldest_date": oldest_proxy_stats,
                "latest_date": latest_proxy_stats,
            },
            "monitoring_daily_stats": {
                "count": monitoring_stats_count,
                "oldest_date": oldest_monitoring_stats,
                "latest_date": latest_monitoring_stats,
            },
        }


# 싱글톤 인스턴스
daily_stats_service = DailyStatsService()
