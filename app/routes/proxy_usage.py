"""
프록시 사용 이력 API 라우트
작성일: 2025-12-18

모니터링 실행 시 프록시 사용 현황과 재시도 이력을 조회하는 API를 제공합니다.
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.proxy_usage_service import proxy_usage_service
from app.schemas.proxy_usage import (
    ProxyUsageLogResponse,
    ProxyUsageStatsResponse,
    ProxyUsageStatItem,
    RetryHistoryResponse,
    ProxyUsageCleanupResult,
)

router = APIRouter(prefix="/api/v1/proxy-usage", tags=["proxy-usage"])


@router.get("/stats", response_model=ProxyUsageStatsResponse)
async def get_proxy_usage_stats(
    date_from: Optional[str] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    schedule_id: Optional[int] = Query(None, description="스케줄 ID 필터"),
    db: Session = Depends(get_db),
) -> ProxyUsageStatsResponse:
    """
    프록시 사용 통계

    프록시별 시도 횟수, 성공률, 평균 응답 시간 등의 통계를 반환합니다.
    """
    return proxy_usage_service.get_usage_stats(
        db=db,
        date_from=date_from,
        date_to=date_to,
        schedule_id=schedule_id,
    )


@router.get("/recent", response_model=List[ProxyUsageLogResponse])
async def get_recent_proxy_usage(
    limit: int = Query(100, ge=1, le=500, description="조회 개수"),
    proxy_host: Optional[str] = Query(None, description="프록시 호스트 필터"),
    success_only: bool = Query(False, description="성공만 조회"),
    db: Session = Depends(get_db),
) -> List[ProxyUsageLogResponse]:
    """
    최근 프록시 사용 이력

    가장 최근 사용된 프록시 이력을 반환합니다.
    """
    return proxy_usage_service.get_recent_usage(
        db=db,
        limit=limit,
        proxy_host=proxy_host,
        success_only=success_only,
    )


@router.get("/retries", response_model=List[RetryHistoryResponse])
async def get_retry_history(
    request_id: Optional[str] = Query(None, description="요청 ID"),
    schedule_id: Optional[int] = Query(None, description="스케줄 ID"),
    date_from: Optional[str] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200, description="조회 개수"),
    db: Session = Depends(get_db),
) -> List[RetryHistoryResponse]:
    """
    재시도 이력

    요청별 재시도 이력을 조회합니다. 각 요청에서 시도된 프록시 목록과 결과를 확인할 수 있습니다.
    """
    return proxy_usage_service.get_retry_history(
        db=db,
        request_id=request_id,
        schedule_id=schedule_id,
        date_from=date_from,
        limit=limit,
    )


@router.get("/failed", response_model=List[ProxyUsageStatItem])
async def get_failed_proxies(
    hours: int = Query(24, ge=1, le=168, description="조회 기간 (시간)"),
    min_failures: int = Query(3, ge=1, description="최소 실패 횟수"),
    db: Session = Depends(get_db),
) -> List[ProxyUsageStatItem]:
    """
    실패 많은 프록시 목록

    지정된 기간 내 실패 횟수가 임계값 이상인 프록시 목록을 반환합니다.
    """
    return proxy_usage_service.get_failed_proxies(
        db=db,
        hours=hours,
        min_failures=min_failures,
    )


@router.delete("/cleanup", response_model=ProxyUsageCleanupResult)
async def cleanup_old_logs(
    days: int = Query(30, ge=1, le=365, description="보존 기간 (일)"),
    db: Session = Depends(get_db),
) -> ProxyUsageCleanupResult:
    """
    오래된 로그 정리

    지정된 기간보다 오래된 프록시 사용 로그를 삭제합니다.
    """
    return proxy_usage_service.cleanup_old_logs(
        db=db,
        days=days,
    )
