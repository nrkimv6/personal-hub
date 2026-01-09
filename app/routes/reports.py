"""
보고서 API 라우트 - LLM 생성 보고서 조회

GET 엔드포인트는 공개, DELETE 엔드포인트는 관리자 인증 필요
"""
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.report_query_service import report_query_service
from app.schemas.report import ReportResponse, ReportList
from app.core.auth import require_admin, UserInfo

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("", response_model=ReportList)
def get_reports(
    report_type: Optional[str] = Query(None, description="보고서 타입 (nightly_cleanup/sleep_now/daily_summary)"),
    period_start: Optional[str] = Query(None, description="기간 시작 (YYYY-MM-DD, 이후 보고서만)"),
    period_end: Optional[str] = Query(None, description="기간 종료 (YYYY-MM-DD, 이전 보고서만)"),
    search: Optional[str] = Query(None, description="제목/요약 검색"),
    sort_by: str = Query("generated_at", description="정렬 기준 (generated_at/period_end)"),
    sort_order: str = Query("desc", description="정렬 순서 (asc/desc)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    db: Session = Depends(get_db),
):
    """
    보고서 목록을 조회합니다.

    - 보고서 타입, 기간별 필터링 지원
    - 제목/요약 검색 지원
    - 정렬 및 페이지네이션 지원
    """
    # 날짜 파싱
    period_start_dt = None
    period_end_dt = None

    if period_start:
        try:
            period_start_dt = datetime.fromisoformat(period_start)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid period_start format. Use YYYY-MM-DD")

    if period_end:
        try:
            period_end_dt = datetime.fromisoformat(period_end)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid period_end format. Use YYYY-MM-DD")

    return report_query_service.get_reports(
        db=db,
        report_type=report_type,
        period_start=period_start_dt,
        period_end=period_end_dt,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.get("/{report_id}", response_model=ReportResponse)
def get_report(report_id: int, db: Session = Depends(get_db)):
    """
    보고서 상세 조회
    """
    report = report_query_service.get_report(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.delete("/{report_id}", status_code=204)
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    보고서를 삭제합니다. (관리자 전용, soft delete)
    """
    success = report_query_service.delete_report(db, report_id)
    if not success:
        raise HTTPException(status_code=404, detail="Report not found")
    return None
