"""
유지보수 API 라우트
작성일: 2025-12-23
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.maintenance_service import maintenance_service
from app.services.daily_stats_service import daily_stats_service
from app.schemas.daily_stats import (
    MaintenanceStatsResponse,
    MaintenanceRunResponse,
    DailyMaintenanceResult,
    CleanupParams,
    ProxyDailyStatsResponse,
    MonitoringDailyStatsResponse,
    ProxyDailyStatsListParams,
    MonitoringDailyStatsListParams,
)

router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])


@router.get("/stats", response_model=MaintenanceStatsResponse)
def get_maintenance_stats(db: Session = Depends(get_db)):
    """
    유지보수 상태 조회

    현재 DB 상태, 일별 통계 상태, 마지막 유지보수 실행 정보를 반환합니다.
    """
    return maintenance_service.get_maintenance_stats(db)


@router.get("/runs", response_model=list[MaintenanceRunResponse])
def get_maintenance_runs(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    유지보수 실행 이력 조회
    """
    return maintenance_service.get_maintenance_runs(db, limit)


@router.post("/daily", response_model=DailyMaintenanceResult)
def run_daily_maintenance(
    target_date: Optional[date] = Query(None, description="집계 대상 날짜 (기본: 어제)"),
    proxy_usage_days: int = Query(30, ge=1, le=365, description="proxy_usage_logs 보존 기간"),
    proxy_history_days: int = Query(90, ge=1, le=365, description="proxy_check_history 보존 기간"),
    monitoring_events_days: int = Query(30, ge=1, le=365, description="monitoring_events 보존 기간"),
    dry_run: bool = Query(False, description="True면 실제 삭제 안 함"),
    run_vacuum: bool = Query(True, description="VACUUM 실행 여부"),
    db: Session = Depends(get_db),
):
    """
    일별 유지보수 수동 실행

    1. 일별 통계 집계
    2. 오래된 로그 정리
    3. DB 최적화 (VACUUM)
    """
    cleanup_params = CleanupParams(
        proxy_usage_days=proxy_usage_days,
        proxy_history_days=proxy_history_days,
        monitoring_events_days=monitoring_events_days,
        dry_run=dry_run,
    )

    return maintenance_service.run_daily_maintenance(
        db,
        target_date=target_date,
        cleanup_params=cleanup_params,
        run_vacuum=run_vacuum,
    )


@router.post("/backfill")
def backfill_daily_stats(
    start_date: date = Query(..., description="시작 날짜"),
    end_date: Optional[date] = Query(None, description="종료 날짜 (기본: 어제)"),
    db: Session = Depends(get_db),
):
    """
    과거 날짜에 대한 일별 통계 백필

    기존에 집계되지 않은 날짜에 대해서만 집계합니다.
    """
    result = maintenance_service.backfill_daily_stats(db, start_date, end_date)
    return {
        "success": True,
        "start_date": start_date,
        "end_date": end_date,
        **result,
    }


# ===== 일별 통계 조회 API =====

@router.get("/proxy-daily-stats", response_model=list[ProxyDailyStatsResponse])
def get_proxy_daily_stats(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    proxy_host: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    프록시 일별 통계 조회
    """
    params = ProxyDailyStatsListParams(
        date_from=date_from,
        date_to=date_to,
        proxy_host=proxy_host,
        limit=limit,
        offset=offset,
    )
    return daily_stats_service.get_proxy_daily_stats(db, params)


@router.get("/monitoring-daily-stats", response_model=list[MonitoringDailyStatsResponse])
def get_monitoring_daily_stats(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    schedule_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    모니터링 일별 통계 조회
    """
    params = MonitoringDailyStatsListParams(
        date_from=date_from,
        date_to=date_to,
        schedule_id=schedule_id,
        limit=limit,
        offset=offset,
    )
    return daily_stats_service.get_monitoring_daily_stats(db, params)


@router.get("/daily-stats-summary")
def get_daily_stats_summary(db: Session = Depends(get_db)):
    """
    일별 통계 요약 정보 조회
    """
    return daily_stats_service.get_stats_summary(db)
