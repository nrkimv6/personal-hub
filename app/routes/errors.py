"""
에러 로그 API 라우트
에러 목록 조회, 통계, 해결 처리
"""
from typing import Optional, List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case, and_

from app.database import get_db
from app.models.error_log import ErrorLog
from app.schemas.error_log import (
    ErrorLogResponse,
    ErrorLogList,
    ErrorLogUpdate,
    ErrorLogStats,
    ErrorLogSourceStats,
    ErrorLogTypeStats,
    ErrorLogHourlyStats,
    ErrorLogStatsResponse,
)

router = APIRouter(prefix="/api/v1/errors", tags=["errors"])


@router.get("", response_model=ErrorLogList)
def get_errors(
    source: Optional[str] = Query(None, description="소스로 필터링 (api/worker/naver/instagram/writing)"),
    severity: Optional[str] = Query(None, description="심각도로 필터링 (critical/error/warning)"),
    error_type: Optional[str] = Query(None, description="에러 타입으로 필터링"),
    resolved: Optional[bool] = Query(None, description="해결 여부로 필터링"),
    date_from: Optional[str] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="메시지 검색"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=200, description="페이지 크기"),
    db: Session = Depends(get_db)
):
    """
    에러 로그 목록을 조회합니다.

    - 소스, 심각도, 에러 타입별 필터링 지원
    - 해결 여부 및 날짜 범위 필터링 지원
    - 메시지 검색 지원
    - 페이지네이션 지원
    """
    query = db.query(ErrorLog)

    # 필터 적용
    if source:
        query = query.filter(ErrorLog.source == source)

    if severity:
        query = query.filter(ErrorLog.severity == severity)

    if error_type:
        query = query.filter(ErrorLog.error_type == error_type)

    if resolved is not None:
        query = query.filter(ErrorLog.resolved == resolved)

    if date_from:
        try:
            from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(ErrorLog.created_at >= from_dt)
        except ValueError:
            pass

    if date_to:
        try:
            to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(ErrorLog.created_at < to_dt)
        except ValueError:
            pass

    if search:
        query = query.filter(ErrorLog.message.ilike(f"%{search}%"))

    # 전체 개수
    total = query.count()

    # 정렬 및 페이지네이션
    items = query.order_by(desc(ErrorLog.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    total_pages = (total + page_size - 1) // page_size

    return ErrorLogList(
        items=[ErrorLogResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/stats", response_model=ErrorLogStatsResponse)
def get_error_stats(
    hours: int = Query(24, ge=1, le=720, description="통계 기간 (시간)"),
    db: Session = Depends(get_db)
):
    """
    에러 통계를 조회합니다.

    - 요약 통계 (총 개수, 심각도별 개수, 해결률)
    - 소스별 통계
    - 에러 타입별 통계 (TOP 10)
    - 시간대별 통계
    """
    since = datetime.utcnow() - timedelta(hours=hours)

    # 기본 쿼리 필터
    base_filter = ErrorLog.created_at >= since

    # 요약 통계
    summary_query = db.query(
        func.count(ErrorLog.id).label("total"),
        func.sum(case((ErrorLog.severity == "critical", 1), else_=0)).label("critical"),
        func.sum(case((ErrorLog.severity == "error", 1), else_=0)).label("error"),
        func.sum(case((ErrorLog.severity == "warning", 1), else_=0)).label("warning"),
        func.sum(case((ErrorLog.resolved == True, 1), else_=0)).label("resolved"),
        func.sum(case((ErrorLog.resolved == False, 1), else_=0)).label("unresolved"),
    ).filter(base_filter).first()

    total = summary_query.total or 0
    resolved_count = summary_query.resolved or 0
    resolve_rate = (resolved_count / total * 100) if total > 0 else 0.0

    summary = ErrorLogStats(
        total_count=total,
        critical_count=summary_query.critical or 0,
        error_count=summary_query.error or 0,
        warning_count=summary_query.warning or 0,
        resolved_count=resolved_count,
        unresolved_count=summary_query.unresolved or 0,
        resolve_rate=round(resolve_rate, 1),
    )

    # 소스별 통계
    source_stats = db.query(
        ErrorLog.source,
        func.count(ErrorLog.id).label("count"),
        func.sum(case((ErrorLog.severity == "critical", 1), else_=0)).label("critical"),
        func.sum(case((ErrorLog.severity == "error", 1), else_=0)).label("error"),
        func.sum(case((ErrorLog.severity == "warning", 1), else_=0)).label("warning"),
    ).filter(base_filter).group_by(ErrorLog.source).all()

    by_source = [
        ErrorLogSourceStats(
            source=row.source,
            count=row.count,
            critical_count=row.critical or 0,
            error_count=row.error or 0,
            warning_count=row.warning or 0,
        )
        for row in source_stats
    ]

    # 에러 타입별 통계 (TOP 10)
    type_stats = db.query(
        ErrorLog.error_type,
        func.count(ErrorLog.id).label("count"),
        func.max(ErrorLog.created_at).label("last_occurred"),
    ).filter(base_filter).group_by(ErrorLog.error_type).order_by(
        desc("count")
    ).limit(10).all()

    by_type = [
        ErrorLogTypeStats(
            error_type=row.error_type,
            count=row.count,
            last_occurred=row.last_occurred,
        )
        for row in type_stats
    ]

    # 시간대별 통계 (최근 24시간만)
    hourly_since = datetime.utcnow() - timedelta(hours=min(hours, 24))
    hourly_stats = db.query(
        func.to_char(ErrorLog.created_at, 'HH24').label("hour"),
        func.count(ErrorLog.id).label("count"),
        func.sum(case((ErrorLog.severity == "critical", 1), else_=0)).label("critical"),
        func.sum(case((ErrorLog.severity == "error", 1), else_=0)).label("error"),
        func.sum(case((ErrorLog.severity == "warning", 1), else_=0)).label("warning"),
    ).filter(ErrorLog.created_at >= hourly_since).group_by("hour").all()

    by_hour = [
        ErrorLogHourlyStats(
            hour=int(row.hour),
            count=row.count,
            critical_count=row.critical or 0,
            error_count=row.error or 0,
            warning_count=row.warning or 0,
        )
        for row in hourly_stats
    ]

    return ErrorLogStatsResponse(
        summary=summary,
        by_source=by_source,
        by_type=by_type,
        by_hour=by_hour,
        period_hours=hours,
    )


@router.get("/sources", response_model=List[str])
def get_error_sources(db: Session = Depends(get_db)):
    """사용 가능한 에러 소스 목록을 반환합니다."""
    sources = db.query(ErrorLog.source).distinct().all()
    return [s[0] for s in sources if s[0]]


@router.get("/types", response_model=List[str])
def get_error_types(
    source: Optional[str] = Query(None, description="소스로 필터링"),
    db: Session = Depends(get_db)
):
    """사용 가능한 에러 타입 목록을 반환합니다."""
    query = db.query(ErrorLog.error_type).distinct()
    if source:
        query = query.filter(ErrorLog.source == source)
    types = query.all()
    return [t[0] for t in types if t[0]]


@router.get("/{error_id}", response_model=ErrorLogResponse)
def get_error_detail(
    error_id: int,
    db: Session = Depends(get_db)
):
    """에러 상세 정보를 조회합니다."""
    error = db.query(ErrorLog).filter(ErrorLog.id == error_id).first()
    if not error:
        raise HTTPException(status_code=404, detail="Error not found")
    return ErrorLogResponse.model_validate(error)


@router.patch("/{error_id}/resolve", response_model=ErrorLogResponse)
def resolve_error(
    error_id: int,
    update: ErrorLogUpdate = Body(...),
    db: Session = Depends(get_db)
):
    """에러를 해결됨으로 처리합니다."""
    error = db.query(ErrorLog).filter(ErrorLog.id == error_id).first()
    if not error:
        raise HTTPException(status_code=404, detail="Error not found")

    if update.resolved is not None:
        error.resolved = update.resolved
        if update.resolved:
            error.resolved_at = datetime.utcnow()
        else:
            error.resolved_at = None

    if update.resolved_by is not None:
        error.resolved_by = update.resolved_by

    if update.notes is not None:
        error.notes = update.notes

    db.commit()
    db.refresh(error)

    return ErrorLogResponse.model_validate(error)


@router.post("/resolve-bulk")
def resolve_errors_bulk(
    error_ids: List[int] = Body(..., embed=True),
    resolved_by: Optional[str] = Body(None, embed=True),
    notes: Optional[str] = Body(None, embed=True),
    db: Session = Depends(get_db)
):
    """여러 에러를 한번에 해결됨으로 처리합니다."""
    now = datetime.utcnow()

    updated = db.query(ErrorLog).filter(
        ErrorLog.id.in_(error_ids)
    ).update({
        ErrorLog.resolved: True,
        ErrorLog.resolved_at: now,
        ErrorLog.resolved_by: resolved_by,
        ErrorLog.notes: notes,
    }, synchronize_session=False)

    db.commit()

    return {"updated": updated, "error_ids": error_ids}


@router.delete("/cleanup")
def cleanup_old_errors(
    days: int = Query(30, ge=1, le=365, description="보관 기간 (일)"),
    resolved_only: bool = Query(True, description="해결된 에러만 삭제"),
    db: Session = Depends(get_db)
):
    """오래된 에러를 정리합니다."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    query = db.query(ErrorLog).filter(ErrorLog.created_at < cutoff)

    if resolved_only:
        query = query.filter(ErrorLog.resolved == True)

    count = query.count()
    query.delete(synchronize_session=False)
    db.commit()

    return {"deleted": count, "cutoff_date": cutoff.isoformat()}
