"""
유지보수 서비스
작성일: 2025-12-23

일별 유지보수 작업을 통합 관리합니다:
1. 일별 통계 집계
2. 오래된 로그 정리
3. DB 최적화 (VACUUM)
"""
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.daily_stats import MaintenanceRun, ProxyDailyStats, MonitoringDailyStats
from app.models.proxy_usage import ProxyUsageLog
from app.models.monitoring_event import MonitoringEvent
from app.models.monitor_schedule import MonitorSchedule
from app.services.daily_stats_service import daily_stats_service
from app.services.proxy_usage_service import proxy_usage_service
from app.schemas.daily_stats import (
    MaintenanceRunResponse,
    MaintenanceStatsResponse,
    DailyMaintenanceResult,
    CleanupParams,
)

logger = logging.getLogger(__name__)


class MaintenanceService:
    """유지보수 서비스"""

    def run_daily_maintenance(
        self,
        db: Session,
        target_date: Optional[date] = None,
        cleanup_params: Optional[CleanupParams] = None,
        run_vacuum: bool = True,
    ) -> DailyMaintenanceResult:
        """
        일별 유지보수 실행

        1. 일별 통계 집계 (어제 데이터)
        2. 오래된 로그 정리
        3. DB 최적화 (VACUUM) - 선택

        Args:
            db: 데이터베이스 세션
            target_date: 집계 대상 날짜 (None이면 어제)
            cleanup_params: 정리 파라미터
            run_vacuum: VACUUM 실행 여부

        Returns:
            유지보수 실행 결과
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        if cleanup_params is None:
            cleanup_params = CleanupParams()

        started_at = datetime.now()

        # 기존 실행 기록 확인
        existing_run = db.query(MaintenanceRun).filter(
            MaintenanceRun.run_date == target_date
        ).first()

        if existing_run and existing_run.status == "success":
            logger.info(f"Maintenance already completed for {target_date}")
            return DailyMaintenanceResult(
                success=True,
                run_id=existing_run.id,
                started_at=existing_run.started_at,
                finished_at=existing_run.finished_at or datetime.now(),
                duration_seconds=existing_run.duration_seconds or 0,
                proxy_stats_aggregated=existing_run.proxy_stats_aggregated,
                monitoring_stats_aggregated=existing_run.monitoring_stats_aggregated,
                proxy_usage_logs_deleted=existing_run.proxy_usage_logs_deleted,
                proxy_check_history_deleted=existing_run.proxy_check_history_deleted,
                monitoring_events_deleted=existing_run.monitoring_events_deleted,
                vacuum_executed=bool(existing_run.vacuum_executed),
                error_message="Already completed",
            )

        # 실행 기록 생성/업데이트
        if existing_run:
            run = existing_run
            run.started_at = started_at
            run.status = "running"
            run.error_message = None
        else:
            run = MaintenanceRun(
                run_date=target_date,
                started_at=started_at,
                status="running",
            )
            db.add(run)
        db.commit()
        db.refresh(run)

        try:
            # 1. 일별 통계 집계
            logger.info(f"Starting daily stats aggregation for {target_date}")
            proxy_stats = daily_stats_service.aggregate_proxy_daily_stats(
                db, target_date, force=True
            )
            monitoring_stats = daily_stats_service.aggregate_monitoring_daily_stats(
                db, target_date, force=True
            )
            run.proxy_stats_aggregated = proxy_stats
            run.monitoring_stats_aggregated = monitoring_stats
            db.commit()

            # 2. 오래된 로그 정리
            if not cleanup_params.dry_run:
                logger.info("Starting log cleanup")
                cleanup_result = self._cleanup_old_logs(db, cleanup_params)
                run.proxy_usage_logs_deleted = cleanup_result["proxy_usage_logs"]
                run.proxy_check_history_deleted = cleanup_result["proxy_check_history"]
                run.monitoring_events_deleted = cleanup_result["monitoring_events"]
                db.commit()
            else:
                logger.info("Dry run - skipping log cleanup")

            # 3. VACUUM (별도 연결 필요)
            if run_vacuum and not cleanup_params.dry_run:
                logger.info("Running VACUUM")
                self._run_vacuum(db)
                run.vacuum_executed = 1
                db.commit()

            # 완료
            finished_at = datetime.now()
            run.finished_at = finished_at
            run.status = "success"
            db.commit()

            logger.info(
                f"Daily maintenance completed for {target_date}: "
                f"proxy_stats={proxy_stats}, monitoring_stats={monitoring_stats}, "
                f"deleted_logs={run.proxy_usage_logs_deleted + run.proxy_check_history_deleted + run.monitoring_events_deleted}"
            )

            return DailyMaintenanceResult(
                success=True,
                run_id=run.id,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(finished_at - started_at).total_seconds(),
                proxy_stats_aggregated=proxy_stats,
                monitoring_stats_aggregated=monitoring_stats,
                proxy_usage_logs_deleted=run.proxy_usage_logs_deleted,
                proxy_check_history_deleted=run.proxy_check_history_deleted,
                monitoring_events_deleted=run.monitoring_events_deleted,
                vacuum_executed=bool(run.vacuum_executed),
            )

        except Exception as e:
            logger.error(f"Daily maintenance failed: {e}")
            run.finished_at = datetime.now()
            run.status = "failed"
            run.error_message = str(e)[:1000]
            db.commit()

            return DailyMaintenanceResult(
                success=False,
                run_id=run.id,
                started_at=started_at,
                finished_at=run.finished_at,
                duration_seconds=(run.finished_at - started_at).total_seconds(),
                proxy_stats_aggregated=run.proxy_stats_aggregated or 0,
                monitoring_stats_aggregated=run.monitoring_stats_aggregated or 0,
                proxy_usage_logs_deleted=run.proxy_usage_logs_deleted or 0,
                proxy_check_history_deleted=run.proxy_check_history_deleted or 0,
                monitoring_events_deleted=run.monitoring_events_deleted or 0,
                vacuum_executed=bool(run.vacuum_executed),
                error_message=str(e),
            )

    def _cleanup_old_logs(
        self,
        db: Session,
        params: CleanupParams,
    ) -> Dict[str, int]:
        """오래된 로그 정리"""
        result = {
            "proxy_usage_logs": 0,
            "proxy_check_history": 0,
            "monitoring_events": 0,
        }

        # 1. proxy_usage_logs 정리
        usage_cutoff = datetime.now() - timedelta(days=params.proxy_usage_days)
        usage_deleted = db.query(ProxyUsageLog).filter(
            ProxyUsageLog.timestamp < usage_cutoff
        ).delete(synchronize_session=False)
        result["proxy_usage_logs"] = usage_deleted
        logger.info(f"Deleted {usage_deleted} proxy_usage_logs older than {params.proxy_usage_days} days")

        # 2. proxy_check_history 정리 (별도 DB이므로 여기서는 카운트만)
        # 실제 삭제는 proxy_db_service.cleanup_old_history() 사용
        # 여기서는 메인 DB만 처리
        result["proxy_check_history"] = 0  # 별도 처리 필요

        # 3. monitoring_events 정리 (비활성 스케줄의 오래된 이벤트만)
        events_cutoff = datetime.now() - timedelta(days=params.monitoring_events_days)

        # 비활성 스케줄 ID 조회
        inactive_schedule_ids = [
            s.id for s in db.query(MonitorSchedule.id).filter(
                MonitorSchedule.is_active == False
            ).all()
        ]

        if inactive_schedule_ids:
            events_deleted = db.query(MonitoringEvent).filter(
                MonitoringEvent.schedule_id.in_(inactive_schedule_ids),
                MonitoringEvent.timestamp < events_cutoff,
            ).delete(synchronize_session=False)
            result["monitoring_events"] = events_deleted
            logger.info(
                f"Deleted {events_deleted} monitoring_events for inactive schedules "
                f"older than {params.monitoring_events_days} days"
            )

        db.commit()
        return result

    def _run_vacuum(self, db: Session) -> None:
        """
        SQLite VACUUM 실행

        Note: VACUUM은 트랜잭션 내에서 실행 불가.
        autocommit 모드로 실행해야 함.
        """
        try:
            # 현재 트랜잭션 커밋
            db.commit()

            # raw connection으로 VACUUM 실행
            connection = db.get_bind().raw_connection()
            connection.execute("VACUUM")
            connection.close()

            logger.info("VACUUM completed successfully")
        except Exception as e:
            logger.warning(f"VACUUM failed (non-critical): {e}")

    def get_maintenance_stats(self, db: Session) -> MaintenanceStatsResponse:
        """유지보수 상태 조회"""
        # 현재 DB 상태
        proxy_usage_count = db.query(func.count(ProxyUsageLog.id)).scalar() or 0
        monitoring_events_count = db.query(func.count(MonitoringEvent.id)).scalar() or 0

        # 일별 통계 상태
        proxy_stats_count = db.query(func.count(ProxyDailyStats.id)).scalar() or 0
        monitoring_stats_count = db.query(func.count(MonitoringDailyStats.id)).scalar() or 0

        oldest_proxy_stats = db.query(func.min(ProxyDailyStats.date)).scalar()
        oldest_monitoring_stats = db.query(func.min(MonitoringDailyStats.date)).scalar()

        # 마지막 유지보수 실행
        last_run = db.query(MaintenanceRun).order_by(
            MaintenanceRun.run_date.desc()
        ).first()

        last_run_response = None
        if last_run:
            last_run_response = MaintenanceRunResponse(
                id=last_run.id,
                run_date=last_run.run_date,
                started_at=last_run.started_at,
                finished_at=last_run.finished_at,
                status=last_run.status,
                proxy_stats_aggregated=last_run.proxy_stats_aggregated or 0,
                monitoring_stats_aggregated=last_run.monitoring_stats_aggregated or 0,
                proxy_usage_logs_deleted=last_run.proxy_usage_logs_deleted or 0,
                proxy_check_history_deleted=last_run.proxy_check_history_deleted or 0,
                monitoring_events_deleted=last_run.monitoring_events_deleted or 0,
                vacuum_executed=bool(last_run.vacuum_executed),
                error_message=last_run.error_message,
                details=json.loads(last_run.details) if last_run.details else None,
            )

        return MaintenanceStatsResponse(
            proxy_usage_logs_count=proxy_usage_count,
            proxy_check_history_count=0,  # 별도 DB
            monitoring_events_count=monitoring_events_count,
            proxy_daily_stats_count=proxy_stats_count,
            monitoring_daily_stats_count=monitoring_stats_count,
            oldest_proxy_stats_date=oldest_proxy_stats,
            oldest_monitoring_stats_date=oldest_monitoring_stats,
            last_maintenance_run=last_run_response,
        )

    def get_maintenance_runs(
        self,
        db: Session,
        limit: int = 30,
    ) -> list[MaintenanceRunResponse]:
        """유지보수 실행 이력 조회"""
        runs = db.query(MaintenanceRun).order_by(
            MaintenanceRun.run_date.desc()
        ).limit(limit).all()

        return [
            MaintenanceRunResponse(
                id=r.id,
                run_date=r.run_date,
                started_at=r.started_at,
                finished_at=r.finished_at,
                status=r.status,
                proxy_stats_aggregated=r.proxy_stats_aggregated or 0,
                monitoring_stats_aggregated=r.monitoring_stats_aggregated or 0,
                proxy_usage_logs_deleted=r.proxy_usage_logs_deleted or 0,
                proxy_check_history_deleted=r.proxy_check_history_deleted or 0,
                monitoring_events_deleted=r.monitoring_events_deleted or 0,
                vacuum_executed=bool(r.vacuum_executed),
                error_message=r.error_message,
                details=json.loads(r.details) if r.details else None,
            )
            for r in runs
        ]

    def backfill_daily_stats(
        self,
        db: Session,
        start_date: date,
        end_date: Optional[date] = None,
    ) -> Dict[str, int]:
        """
        과거 날짜에 대한 일별 통계 백필

        Args:
            db: 데이터베이스 세션
            start_date: 시작 날짜
            end_date: 종료 날짜 (None이면 어제까지)

        Returns:
            {"proxy": 집계 수, "monitoring": 집계 수}
        """
        if end_date is None:
            end_date = date.today() - timedelta(days=1)

        proxy_total, monitoring_total = daily_stats_service.aggregate_date_range(
            db, start_date, end_date, force=False
        )

        logger.info(
            f"Backfill completed: {start_date} ~ {end_date}, "
            f"proxy={proxy_total}, monitoring={monitoring_total}"
        )

        return {
            "proxy": proxy_total,
            "monitoring": monitoring_total,
        }


# 싱글톤 인스턴스
maintenance_service = MaintenanceService()
