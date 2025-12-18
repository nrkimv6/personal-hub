"""
프록시 사용 이력 서비스
작성일: 2025-12-18

모니터링 실행 시 프록시 사용 현황과 재시도 이력을 추적합니다.
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, case

from app.models.proxy_usage import ProxyUsageLog
from app.models.monitor_schedule import MonitorSchedule
from app.models.biz_item import BizItem
from app.models.business import Business
from app.schemas.proxy_usage import (
    ProxyUsageLogCreate,
    ProxyUsageLogResponse,
    ProxyUsageStatItem,
    ProxyUsageStatsResponse,
    RetryHistoryResponse,
    RetryAttemptInfo,
    ProxyUsageCleanupResult,
)

logger = logging.getLogger(__name__)


class ProxyUsageService:
    """프록시 사용 이력 서비스"""

    def log_attempt(
        self,
        db: Session,
        log_data: ProxyUsageLogCreate
    ) -> ProxyUsageLog:
        """
        프록시 시도 기록

        Args:
            db: 데이터베이스 세션
            log_data: 로그 생성 데이터

        Returns:
            생성된 ProxyUsageLog 객체
        """
        proxy_host = ProxyUsageLog.extract_host(log_data.proxy_url)

        log = ProxyUsageLog(
            schedule_id=log_data.schedule_id,
            monitoring_event_id=log_data.monitoring_event_id,
            proxy_url=log_data.proxy_url,
            proxy_host=proxy_host,
            attempt_number=log_data.attempt_number,
            request_id=log_data.request_id,
            success=1 if log_data.success else 0,
            http_status=log_data.http_status,
            error_type=log_data.error_type,
            error_message=log_data.error_message[:500] if log_data.error_message else None,
            response_time_ms=log_data.response_time_ms,
            target_url=log_data.target_url,
            fetch_method=log_data.fetch_method,
        )

        db.add(log)
        db.commit()
        db.refresh(log)

        return log

    def link_to_event(
        self,
        db: Session,
        request_id: str,
        event_id: int
    ) -> int:
        """
        성공 시 monitoring_event와 연결

        Args:
            db: 데이터베이스 세션
            request_id: 요청 식별자
            event_id: 연결할 모니터링 이벤트 ID

        Returns:
            업데이트된 로그 수
        """
        result = db.query(ProxyUsageLog).filter(
            ProxyUsageLog.request_id == request_id
        ).update(
            {"monitoring_event_id": event_id},
            synchronize_session=False
        )
        db.commit()
        return result

    def get_usage_stats(
        self,
        db: Session,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        schedule_id: Optional[int] = None,
    ) -> ProxyUsageStatsResponse:
        """
        프록시별 사용 통계

        Args:
            db: 데이터베이스 세션
            date_from: 시작 날짜 (YYYY-MM-DD)
            date_to: 종료 날짜 (YYYY-MM-DD)
            schedule_id: 스케줄 ID 필터

        Returns:
            프록시 사용 통계 응답
        """
        # 기본 쿼리 필터
        filters = []

        if date_from:
            start_dt = datetime.strptime(date_from, "%Y-%m-%d")
            filters.append(ProxyUsageLog.timestamp >= start_dt)

        if date_to:
            end_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            filters.append(ProxyUsageLog.timestamp < end_dt)

        if schedule_id:
            filters.append(ProxyUsageLog.schedule_id == schedule_id)

        base_query = db.query(ProxyUsageLog)
        if filters:
            base_query = base_query.filter(and_(*filters))

        # 전체 통계
        total_attempts = base_query.count()
        success_count = base_query.filter(ProxyUsageLog.success == 1).count()
        overall_success_rate = (success_count / total_attempts * 100) if total_attempts > 0 else 0.0

        # 프록시별 통계
        proxy_stats_query = db.query(
            ProxyUsageLog.proxy_host,
            func.count(ProxyUsageLog.id).label("total_attempts"),
            func.sum(ProxyUsageLog.success).label("success_count"),
            func.avg(
                case(
                    [(ProxyUsageLog.success == 1, ProxyUsageLog.response_time_ms)],
                    else_=None
                )
            ).label("avg_response_time_ms"),
            func.max(ProxyUsageLog.timestamp).label("last_used_at"),
        ).group_by(ProxyUsageLog.proxy_host)

        if filters:
            proxy_stats_query = proxy_stats_query.filter(and_(*filters))

        proxy_stats_query = proxy_stats_query.order_by(desc("total_attempts")).limit(100)

        by_proxy = []
        proxy_hosts = set()

        for row in proxy_stats_query.all():
            if row.proxy_host:
                proxy_hosts.add(row.proxy_host)
                total = row.total_attempts or 0
                success = int(row.success_count or 0)
                fail = total - success
                success_rate = (success / total * 100) if total > 0 else 0.0

                # 에러 유형별 카운트 조회
                error_query = db.query(
                    ProxyUsageLog.error_type,
                    func.count(ProxyUsageLog.id).label("count")
                ).filter(
                    ProxyUsageLog.proxy_host == row.proxy_host,
                    ProxyUsageLog.success == 0,
                    ProxyUsageLog.error_type.isnot(None)
                )
                if filters:
                    error_query = error_query.filter(and_(*filters))

                error_types = {
                    r.error_type: r.count
                    for r in error_query.group_by(ProxyUsageLog.error_type).all()
                }

                by_proxy.append(ProxyUsageStatItem(
                    proxy_host=row.proxy_host,
                    total_attempts=total,
                    success_count=success,
                    fail_count=fail,
                    success_rate=round(success_rate, 1),
                    avg_response_time_ms=round(row.avg_response_time_ms, 1) if row.avg_response_time_ms else None,
                    last_used_at=row.last_used_at,
                    error_types=error_types,
                ))

        # 전체 에러 유형별 분포
        error_type_query = db.query(
            ProxyUsageLog.error_type,
            func.count(ProxyUsageLog.id).label("count")
        ).filter(
            ProxyUsageLog.success == 0,
            ProxyUsageLog.error_type.isnot(None)
        )
        if filters:
            error_type_query = error_type_query.filter(and_(*filters))

        by_error_type = {
            r.error_type: r.count
            for r in error_type_query.group_by(ProxyUsageLog.error_type).all()
        }

        return ProxyUsageStatsResponse(
            total_proxies_used=len(proxy_hosts),
            total_attempts=total_attempts,
            overall_success_rate=round(overall_success_rate, 1),
            by_proxy=by_proxy,
            by_error_type=by_error_type,
        )

    def get_recent_usage(
        self,
        db: Session,
        limit: int = 100,
        proxy_host: Optional[str] = None,
        success_only: bool = False,
    ) -> List[ProxyUsageLogResponse]:
        """
        최근 사용 이력

        Args:
            db: 데이터베이스 세션
            limit: 조회 개수
            proxy_host: 프록시 호스트 필터
            success_only: 성공만 조회

        Returns:
            프록시 사용 로그 목록
        """
        query = db.query(ProxyUsageLog)

        if proxy_host:
            query = query.filter(ProxyUsageLog.proxy_host == proxy_host)

        if success_only:
            query = query.filter(ProxyUsageLog.success == 1)

        logs = query.order_by(desc(ProxyUsageLog.timestamp)).limit(limit).all()

        return [
            ProxyUsageLogResponse(
                id=log.id,
                schedule_id=log.schedule_id,
                monitoring_event_id=log.monitoring_event_id,
                proxy_url=log.proxy_url,
                proxy_host=log.proxy_host,
                attempt_number=log.attempt_number,
                request_id=log.request_id,
                success=log.is_success,
                http_status=log.http_status,
                error_type=log.error_type,
                error_message=log.error_message,
                response_time_ms=log.response_time_ms,
                target_url=log.target_url,
                fetch_method=log.fetch_method,
                timestamp=log.timestamp,
            )
            for log in logs
        ]

    def get_retry_history(
        self,
        db: Session,
        request_id: Optional[str] = None,
        schedule_id: Optional[int] = None,
        date_from: Optional[str] = None,
        limit: int = 50,
    ) -> List[RetryHistoryResponse]:
        """
        재시도 이력 조회 (request_id로 그룹핑)

        Args:
            db: 데이터베이스 세션
            request_id: 요청 ID (특정 요청 조회)
            schedule_id: 스케줄 ID 필터
            date_from: 시작 날짜
            limit: 조회 개수

        Returns:
            재시도 이력 목록
        """
        # request_id별 그룹 조회
        subquery = db.query(
            ProxyUsageLog.request_id,
            func.min(ProxyUsageLog.timestamp).label("started_at"),
            func.max(ProxyUsageLog.timestamp).label("completed_at"),
            func.count(ProxyUsageLog.id).label("total_attempts"),
            func.max(ProxyUsageLog.success).label("final_success"),
            func.min(ProxyUsageLog.schedule_id).label("schedule_id"),
        ).filter(
            ProxyUsageLog.request_id.isnot(None)
        )

        if request_id:
            subquery = subquery.filter(ProxyUsageLog.request_id == request_id)

        if schedule_id:
            subquery = subquery.filter(ProxyUsageLog.schedule_id == schedule_id)

        if date_from:
            start_dt = datetime.strptime(date_from, "%Y-%m-%d")
            subquery = subquery.filter(ProxyUsageLog.timestamp >= start_dt)

        subquery = subquery.group_by(
            ProxyUsageLog.request_id
        ).order_by(
            desc("completed_at")
        ).limit(limit)

        results = []

        for row in subquery.all():
            # 상세 시도 정보 조회
            attempts_query = db.query(ProxyUsageLog).filter(
                ProxyUsageLog.request_id == row.request_id
            ).order_by(ProxyUsageLog.attempt_number).all()

            # 스케줄 정보 조회 (업체/상품명)
            schedule = db.query(MonitorSchedule).filter(
                MonitorSchedule.id == row.schedule_id
            ).first()

            business_name = None
            biz_item_name = None

            if schedule and schedule.biz_item:
                biz_item_name = schedule.biz_item.name
                if schedule.biz_item.business:
                    business_name = schedule.biz_item.business.name

            # 소요 시간 계산
            duration_ms = 0
            if row.started_at and row.completed_at:
                duration_ms = int((row.completed_at - row.started_at).total_seconds() * 1000)

            attempts = [
                RetryAttemptInfo(
                    attempt_number=log.attempt_number,
                    proxy_url=log.proxy_url,
                    proxy_host=log.proxy_host,
                    success=log.is_success,
                    http_status=log.http_status,
                    error_type=log.error_type,
                    error_message=log.error_message,
                    response_time_ms=log.response_time_ms,
                    timestamp=log.timestamp,
                )
                for log in attempts_query
            ]

            results.append(RetryHistoryResponse(
                request_id=row.request_id,
                schedule_id=row.schedule_id,
                business_name=business_name,
                biz_item_name=biz_item_name,
                total_attempts=row.total_attempts,
                final_success=bool(row.final_success),
                attempts=attempts,
                started_at=row.started_at,
                completed_at=row.completed_at,
                total_duration_ms=duration_ms,
            ))

        return results

    def get_failed_proxies(
        self,
        db: Session,
        hours: int = 24,
        min_failures: int = 3,
    ) -> List[ProxyUsageStatItem]:
        """
        최근 N시간 내 실패 많은 프록시

        Args:
            db: 데이터베이스 세션
            hours: 조회 기간 (시간)
            min_failures: 최소 실패 횟수

        Returns:
            실패 많은 프록시 통계 목록
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        query = db.query(
            ProxyUsageLog.proxy_host,
            func.count(ProxyUsageLog.id).label("total_attempts"),
            func.sum(ProxyUsageLog.success).label("success_count"),
            func.sum(case([(ProxyUsageLog.success == 0, 1)], else_=0)).label("fail_count"),
            func.avg(
                case(
                    [(ProxyUsageLog.success == 1, ProxyUsageLog.response_time_ms)],
                    else_=None
                )
            ).label("avg_response_time_ms"),
            func.max(ProxyUsageLog.timestamp).label("last_used_at"),
        ).filter(
            ProxyUsageLog.timestamp >= cutoff,
            ProxyUsageLog.proxy_host.isnot(None),
        ).group_by(
            ProxyUsageLog.proxy_host
        ).having(
            func.sum(case([(ProxyUsageLog.success == 0, 1)], else_=0)) >= min_failures
        ).order_by(
            desc("fail_count")
        ).limit(50)

        results = []

        for row in query.all():
            total = row.total_attempts or 0
            success = int(row.success_count or 0)
            fail = int(row.fail_count or 0)
            success_rate = (success / total * 100) if total > 0 else 0.0

            # 에러 유형별 카운트
            error_query = db.query(
                ProxyUsageLog.error_type,
                func.count(ProxyUsageLog.id).label("count")
            ).filter(
                ProxyUsageLog.proxy_host == row.proxy_host,
                ProxyUsageLog.success == 0,
                ProxyUsageLog.error_type.isnot(None),
                ProxyUsageLog.timestamp >= cutoff,
            ).group_by(ProxyUsageLog.error_type).all()

            error_types = {r.error_type: r.count for r in error_query}

            results.append(ProxyUsageStatItem(
                proxy_host=row.proxy_host,
                total_attempts=total,
                success_count=success,
                fail_count=fail,
                success_rate=round(success_rate, 1),
                avg_response_time_ms=round(row.avg_response_time_ms, 1) if row.avg_response_time_ms else None,
                last_used_at=row.last_used_at,
                error_types=error_types,
            ))

        return results

    def cleanup_old_logs(
        self,
        db: Session,
        days: int = 30
    ) -> ProxyUsageCleanupResult:
        """
        오래된 로그 정리

        Args:
            db: 데이터베이스 세션
            days: 보존 기간 (일)

        Returns:
            정리 결과
        """
        cutoff = datetime.utcnow() - timedelta(days=days)

        before_count = db.query(func.count(ProxyUsageLog.id)).scalar() or 0

        deleted = db.query(ProxyUsageLog).filter(
            ProxyUsageLog.timestamp < cutoff
        ).delete(synchronize_session=False)

        db.commit()

        after_count = db.query(func.count(ProxyUsageLog.id)).scalar() or 0

        logger.info(f"Cleaned up {deleted} old proxy usage logs (before: {before_count}, after: {after_count})")

        return ProxyUsageCleanupResult(
            deleted_count=deleted,
            before_count=before_count,
            after_count=after_count,
            cutoff_date=cutoff,
        )


# 싱글톤 인스턴스
proxy_usage_service = ProxyUsageService()
