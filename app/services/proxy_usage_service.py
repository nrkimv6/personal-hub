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

        # 전체 통계 + 성공 카운트를 단일 쿼리로
        stats_query = db.query(
            func.count(ProxyUsageLog.id).label("total"),
            func.sum(ProxyUsageLog.success).label("success"),
        )
        if filters:
            stats_query = stats_query.filter(and_(*filters))
        stats_result = stats_query.first()
        total_attempts = stats_result.total or 0
        success_count = int(stats_result.success or 0)
        overall_success_rate = (success_count / total_attempts * 100) if total_attempts > 0 else 0.0

        # 프록시별 통계
        proxy_stats_query = db.query(
            ProxyUsageLog.proxy_host,
            func.count(ProxyUsageLog.id).label("total_attempts"),
            func.sum(ProxyUsageLog.success).label("success_count"),
            func.avg(
                case(
                    (ProxyUsageLog.success == 1, ProxyUsageLog.response_time_ms),
                    else_=None
                )
            ).label("avg_response_time_ms"),
            func.max(ProxyUsageLog.timestamp).label("last_used_at"),
        ).group_by(ProxyUsageLog.proxy_host)

        if filters:
            proxy_stats_query = proxy_stats_query.filter(and_(*filters))

        proxy_stats_query = proxy_stats_query.order_by(desc("total_attempts")).limit(100)
        proxy_stats_rows = proxy_stats_query.all()

        # 프록시 호스트 목록 수집
        proxy_hosts = {row.proxy_host for row in proxy_stats_rows if row.proxy_host}

        # [N+1 해결] 모든 프록시의 에러 유형을 단일 쿼리로 조회
        error_by_proxy: Dict[str, Dict[str, int]] = {host: {} for host in proxy_hosts}
        if proxy_hosts:
            all_errors_query = db.query(
                ProxyUsageLog.proxy_host,
                ProxyUsageLog.error_type,
                func.count(ProxyUsageLog.id).label("count")
            ).filter(
                ProxyUsageLog.proxy_host.in_(proxy_hosts),
                ProxyUsageLog.success == 0,
                ProxyUsageLog.error_type.isnot(None)
            )
            if filters:
                all_errors_query = all_errors_query.filter(and_(*filters))

            all_errors = all_errors_query.group_by(
                ProxyUsageLog.proxy_host,
                ProxyUsageLog.error_type
            ).all()

            for row in all_errors:
                if row.proxy_host in error_by_proxy:
                    error_by_proxy[row.proxy_host][row.error_type] = row.count

        # 프록시별 통계 응답 생성
        by_proxy = []
        for row in proxy_stats_rows:
            if row.proxy_host:
                total = row.total_attempts or 0
                success = int(row.success_count or 0)
                fail = total - success
                success_rate = (success / total * 100) if total > 0 else 0.0

                by_proxy.append(ProxyUsageStatItem(
                    proxy_host=row.proxy_host,
                    total_attempts=total,
                    success_count=success,
                    fail_count=fail,
                    success_rate=round(success_rate, 1),
                    avg_response_time_ms=round(row.avg_response_time_ms, 1) if row.avg_response_time_ms else None,
                    last_used_at=row.last_used_at,
                    error_types=error_by_proxy.get(row.proxy_host, {}),
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
        from collections import defaultdict

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

        rows = subquery.all()
        if not rows:
            return []

        # request_id, schedule_id 목록 수집
        request_ids = [row.request_id for row in rows]
        schedule_ids = {row.schedule_id for row in rows if row.schedule_id}

        # [N+1 해결] 모든 request_id의 상세 시도 정보를 단일 쿼리로 조회
        all_attempts = db.query(ProxyUsageLog).filter(
            ProxyUsageLog.request_id.in_(request_ids)
        ).order_by(
            ProxyUsageLog.request_id,
            ProxyUsageLog.attempt_number
        ).all()

        # request_id별로 그룹핑
        attempts_by_request: Dict[str, List[ProxyUsageLog]] = defaultdict(list)
        for log in all_attempts:
            attempts_by_request[log.request_id].append(log)

        # [N+1 해결] 모든 schedule의 정보를 단일 쿼리로 조회
        schedule_info: Dict[int, tuple] = {}
        if schedule_ids:
            schedules = db.query(
                MonitorSchedule.id,
                BizItem.name.label("biz_item_name"),
                Business.name.label("business_name"),
            ).outerjoin(
                BizItem, MonitorSchedule.biz_item_id == BizItem.id
            ).outerjoin(
                Business, BizItem.business_id == Business.id
            ).filter(
                MonitorSchedule.id.in_(schedule_ids)
            ).all()

            for s in schedules:
                schedule_info[s.id] = (s.business_name, s.biz_item_name)

        results = []
        for row in rows:
            business_name, biz_item_name = schedule_info.get(row.schedule_id, (None, None))

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
                for log in attempts_by_request.get(row.request_id, [])
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
        cutoff = datetime.now() - timedelta(hours=hours)

        query = db.query(
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
            func.max(ProxyUsageLog.timestamp).label("last_used_at"),
        ).filter(
            ProxyUsageLog.timestamp >= cutoff,
            ProxyUsageLog.proxy_host.isnot(None),
        ).group_by(
            ProxyUsageLog.proxy_host
        ).having(
            func.sum(case((ProxyUsageLog.success == 0, 1), else_=0)) >= min_failures
        ).order_by(
            desc("fail_count")
        ).limit(50)

        rows = query.all()

        # 프록시 호스트 목록 수집
        proxy_hosts = {row.proxy_host for row in rows if row.proxy_host}

        # [N+1 해결] 모든 프록시의 에러 유형을 단일 쿼리로 조회
        error_by_proxy: Dict[str, Dict[str, int]] = {host: {} for host in proxy_hosts}
        if proxy_hosts:
            all_errors = db.query(
                ProxyUsageLog.proxy_host,
                ProxyUsageLog.error_type,
                func.count(ProxyUsageLog.id).label("count")
            ).filter(
                ProxyUsageLog.proxy_host.in_(proxy_hosts),
                ProxyUsageLog.success == 0,
                ProxyUsageLog.error_type.isnot(None),
                ProxyUsageLog.timestamp >= cutoff,
            ).group_by(
                ProxyUsageLog.proxy_host,
                ProxyUsageLog.error_type
            ).all()

            for err_row in all_errors:
                if err_row.proxy_host in error_by_proxy:
                    error_by_proxy[err_row.proxy_host][err_row.error_type] = err_row.count

        results = []
        for row in rows:
            total = row.total_attempts or 0
            success = int(row.success_count or 0)
            fail = int(row.fail_count or 0)
            success_rate = (success / total * 100) if total > 0 else 0.0

            results.append(ProxyUsageStatItem(
                proxy_host=row.proxy_host,
                total_attempts=total,
                success_count=success,
                fail_count=fail,
                success_rate=round(success_rate, 1),
                avg_response_time_ms=round(row.avg_response_time_ms, 1) if row.avg_response_time_ms else None,
                last_used_at=row.last_used_at,
                error_types=error_by_proxy.get(row.proxy_host, {}),
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
        cutoff = datetime.now() - timedelta(days=days)

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

    def get_timeout_counts(
        self,
        db: Session,
        hours: int = 24,
        min_timeouts: int = 1,
    ) -> Dict[str, int]:
        """
        최근 N시간 내 프록시별 timeout 카운트 조회

        워커 시작 시 slow_count 초기화에 사용

        Args:
            db: 데이터베이스 세션
            hours: 조회 기간 (시간)
            min_timeouts: 최소 timeout 횟수

        Returns:
            {proxy_host: timeout_count} 딕셔너리
        """
        cutoff = datetime.now() - timedelta(hours=hours)

        query = db.query(
            ProxyUsageLog.proxy_host,
            func.count(ProxyUsageLog.id).label("timeout_count"),
        ).filter(
            ProxyUsageLog.timestamp >= cutoff,
            ProxyUsageLog.proxy_host.isnot(None),
            ProxyUsageLog.error_type == "timeout",
        ).group_by(
            ProxyUsageLog.proxy_host
        ).having(
            func.count(ProxyUsageLog.id) >= min_timeouts
        )

        return {row.proxy_host: row.timeout_count for row in query.all()}

    def get_high_failure_proxy_hosts(
        self,
        db: Session,
        hours: int = 6,
        min_attempts: int = 3,
        max_success_rate: float = 0.2,
    ) -> List[str]:
        """
        최근 N시간 동안 실패율 높은 프록시 호스트 목록 조회

        풀 갱신 시 제외할 프록시 필터링에 사용

        Args:
            db: 데이터베이스 세션
            hours: 조회 기간 (시간)
            min_attempts: 최소 시도 횟수 (신뢰도 확보)
            max_success_rate: 최대 성공률 (이 값 이하면 실패로 간주, 0.0~1.0)

        Returns:
            실패율 높은 프록시 호스트 목록
        """
        cutoff = datetime.now() - timedelta(hours=hours)

        # 프록시별 성공률 계산
        query = db.query(
            ProxyUsageLog.proxy_host,
            func.count(ProxyUsageLog.id).label("total_attempts"),
            func.sum(ProxyUsageLog.success).label("success_count"),
        ).filter(
            ProxyUsageLog.timestamp >= cutoff,
            ProxyUsageLog.proxy_host.isnot(None),
            # 특수 프록시 제외 (direct, socks4 프로토콜 표시 등)
            ProxyUsageLog.proxy_host.notin_(["direct", "socks4", "socks5", "http", "https"]),
        ).group_by(
            ProxyUsageLog.proxy_host
        ).having(
            func.count(ProxyUsageLog.id) >= min_attempts
        )

        high_failure_hosts = []
        for row in query.all():
            total = row.total_attempts or 0
            success = int(row.success_count or 0)
            if total > 0:
                success_rate = success / total
                if success_rate <= max_success_rate:
                    high_failure_hosts.append(row.proxy_host)
                    logger.debug(
                        f"High failure proxy: {row.proxy_host} "
                        f"(success_rate={success_rate:.1%}, attempts={total})"
                    )

        if high_failure_hosts:
            logger.info(
                f"Found {len(high_failure_hosts)} high-failure proxies "
                f"(last {hours}h, success_rate <= {max_success_rate:.0%})"
            )

        return high_failure_hosts

    def get_proxy_usage_stats_for_sync(
        self,
        db: Session,
        hours: int = 24,
        min_attempts: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        proxies 테이블 동기화용 프록시별 사용 통계 조회

        Args:
            db: 데이터베이스 세션
            hours: 조회 기간 (시간)
            min_attempts: 최소 시도 횟수

        Returns:
            프록시별 통계 목록
            [{
                "proxy_host": "1.2.3.4",
                "success_count": 10,
                "fail_count": 5,
                "total_attempts": 15,
                "avg_response_time_ms": 500,
                "last_used_at": datetime
            }, ...]
        """
        cutoff = datetime.now() - timedelta(hours=hours)

        query = db.query(
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
            func.max(ProxyUsageLog.timestamp).label("last_used_at"),
        ).filter(
            ProxyUsageLog.timestamp >= cutoff,
            ProxyUsageLog.proxy_host.isnot(None),
            # 특수 프록시 제외
            ProxyUsageLog.proxy_host.notin_(["direct", "socks4", "socks5", "http", "https"]),
        ).group_by(
            ProxyUsageLog.proxy_host
        ).having(
            func.count(ProxyUsageLog.id) >= min_attempts
        )

        return [
            {
                "proxy_host": row.proxy_host,
                "success_count": int(row.success_count or 0),
                "fail_count": int(row.fail_count or 0),
                "total_attempts": row.total_attempts or 0,
                "avg_response_time_ms": row.avg_response_time_ms,
                "last_used_at": row.last_used_at,
            }
            for row in query.all()
        ]


# 싱글톤 인스턴스
proxy_usage_service = ProxyUsageService()
