"""
일별 통계 스키마
작성일: 2025-12-23
"""
from datetime import date, datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel


class ProxyDailyStatsBase(BaseModel):
    """프록시 일별 통계 기본 스키마"""
    date: date
    proxy_host: str
    total_attempts: int = 0
    success_count: int = 0
    fail_count: int = 0
    avg_response_time_ms: Optional[float] = None
    min_response_time_ms: Optional[float] = None
    max_response_time_ms: Optional[float] = None
    error_types: Optional[Dict[str, int]] = None


class ProxyDailyStatsResponse(ProxyDailyStatsBase):
    """프록시 일별 통계 응답"""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class MonitoringDailyStatsBase(BaseModel):
    """모니터링 일별 통계 기본 스키마"""
    date: date
    schedule_id: int
    check_count: int = 0
    success_count: int = 0
    error_count: int = 0
    available_detected: int = 0
    booking_triggered: int = 0
    booking_success: int = 0
    avg_response_time_ms: Optional[float] = None


class MonitoringDailyStatsResponse(MonitoringDailyStatsBase):
    """모니터링 일별 통계 응답"""
    id: int
    created_at: datetime

    # 추가 정보 (조인)
    business_name: Optional[str] = None
    biz_item_name: Optional[str] = None

    class Config:
        from_attributes = True


class MaintenanceRunBase(BaseModel):
    """유지보수 실행 기본 스키마"""
    run_date: date
    status: str = "running"


class MaintenanceRunResponse(MaintenanceRunBase):
    """유지보수 실행 응답"""
    id: int
    started_at: datetime
    finished_at: Optional[datetime] = None

    # 집계 결과
    proxy_stats_aggregated: int = 0
    monitoring_stats_aggregated: int = 0

    # 정리 결과
    proxy_usage_logs_deleted: int = 0
    proxy_check_history_deleted: int = 0
    monitoring_events_deleted: int = 0

    # 최적화
    vacuum_executed: bool = False

    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class MaintenanceStatsResponse(BaseModel):
    """유지보수 상태 응답"""
    # 현재 DB 상태
    proxy_usage_logs_count: int
    proxy_check_history_count: int
    monitoring_events_count: int

    # 일별 통계 상태
    proxy_daily_stats_count: int
    monitoring_daily_stats_count: int
    oldest_proxy_stats_date: Optional[date] = None
    oldest_monitoring_stats_date: Optional[date] = None

    # 마지막 유지보수
    last_maintenance_run: Optional[MaintenanceRunResponse] = None


class DailyMaintenanceResult(BaseModel):
    """일별 유지보수 실행 결과"""
    success: bool
    run_id: int
    started_at: datetime
    finished_at: datetime
    duration_seconds: float

    # 집계 결과
    proxy_stats_aggregated: int
    monitoring_stats_aggregated: int

    # 정리 결과
    proxy_usage_logs_deleted: int
    proxy_check_history_deleted: int
    monitoring_events_deleted: int

    # VACUUM
    vacuum_executed: bool

    error_message: Optional[str] = None


class AggregationParams(BaseModel):
    """집계 파라미터"""
    target_date: Optional[date] = None  # None이면 어제 날짜
    force: bool = False  # True면 기존 집계 덮어쓰기


class CleanupParams(BaseModel):
    """정리 파라미터"""
    proxy_usage_days: int = 30  # proxy_usage_logs 보존 기간
    proxy_history_days: int = 90  # proxy_check_history 보존 기간
    monitoring_events_days: int = 30  # monitoring_events 보존 기간 (비활성 스케줄만)
    dry_run: bool = False  # True면 실제 삭제 안 함


class ProxyDailyStatsListParams(BaseModel):
    """프록시 일별 통계 조회 파라미터"""
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    proxy_host: Optional[str] = None
    limit: int = 100
    offset: int = 0


class MonitoringDailyStatsListParams(BaseModel):
    """모니터링 일별 통계 조회 파라미터"""
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    schedule_id: Optional[int] = None
    limit: int = 100
    offset: int = 0
