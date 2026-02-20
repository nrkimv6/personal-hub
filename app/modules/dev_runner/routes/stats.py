"""통계 API"""

from fastapi import APIRouter, Query
from typing import List, Optional

from app.modules.dev_runner.schemas import StatsResponse, HistoryEntry, DuplicateTaskResponse
from app.modules.dev_runner.services.db_service import db_service

router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    since: Optional[str] = Query(None, description="이 시간 이후 task만 집계 (ISO format)")
):
    """시스템 통계 조회"""
    return db_service.get_stats(since=since)


@router.get("/history", response_model=List[HistoryEntry])
async def get_history(
    days: int = Query(30, ge=1, le=365, description="조회할 일수")
):
    """작업 히스토리 조회 (날짜별 집계)"""
    return db_service.get_history(days=days)


@router.get("/duplicates", response_model=List[DuplicateTaskResponse])
async def get_duplicates(
    min_count: int = Query(2, ge=2, description="최소 중복 개수")
):
    """중복 작업 분석"""
    return db_service.find_duplicate_tasks(min_count=min_count)


__all__ = ['router']
