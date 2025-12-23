"""
일별 통계 모델
작성일: 2025-12-23
"""
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Date, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.models.base import Base


class ProxyDailyStats(Base):
    """프록시 일별 통계 테이블"""
    __tablename__ = "proxy_daily_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    proxy_host = Column(Text, nullable=False)

    # 통계
    total_attempts = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    avg_response_time_ms = Column(Float, nullable=True)
    min_response_time_ms = Column(Float, nullable=True)
    max_response_time_ms = Column(Float, nullable=True)

    # 에러 유형별 카운트 (JSON)
    error_types = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('idx_proxy_daily_stats_date', 'date'),
        Index('idx_proxy_daily_stats_proxy_host', 'proxy_host'),
    )

    @property
    def success_rate(self) -> float:
        """성공률 계산"""
        if self.total_attempts and self.total_attempts > 0:
            return round(self.success_count / self.total_attempts * 100, 1)
        return 0.0


class MonitoringDailyStats(Base):
    """모니터링 일별 통계 테이블"""
    __tablename__ = "monitoring_daily_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    schedule_id = Column(
        Integer,
        ForeignKey("monitor_schedules.id", ondelete="CASCADE"),
        nullable=False
    )

    # 통계
    check_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    available_detected = Column(Integer, default=0)
    booking_triggered = Column(Integer, default=0)
    booking_success = Column(Integer, default=0)
    avg_response_time_ms = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.now)

    # 관계
    schedule = relationship("MonitorSchedule")

    __table_args__ = (
        Index('idx_monitoring_daily_stats_date', 'date'),
        Index('idx_monitoring_daily_stats_schedule_id', 'schedule_id'),
    )


class MaintenanceRun(Base):
    """유지보수 실행 로그 테이블"""
    __tablename__ = "maintenance_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_date = Column(Date, nullable=False, unique=True)
    started_at = Column(DateTime, nullable=False, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, default="running")  # running, success, failed

    # 집계 결과
    proxy_stats_aggregated = Column(Integer, default=0)
    monitoring_stats_aggregated = Column(Integer, default=0)

    # 정리 결과
    proxy_usage_logs_deleted = Column(Integer, default=0)
    proxy_check_history_deleted = Column(Integer, default=0)
    monitoring_events_deleted = Column(Integer, default=0)

    # 최적화
    vacuum_executed = Column(Integer, default=0)  # 0/1

    error_message = Column(Text, nullable=True)
    details = Column(Text, nullable=True)  # JSON

    __table_args__ = (
        Index('idx_maintenance_runs_date', 'run_date'),
    )

    @property
    def duration_seconds(self) -> float | None:
        """실행 시간 (초)"""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
