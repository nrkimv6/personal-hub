"""Report query service for API endpoints."""
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import func, desc, asc
from sqlalchemy.orm import Session

from app.modules.reports.models.generated_report import GeneratedReport
from app.schemas.report import ReportList, ReportListItem, ReportResponse

logger = logging.getLogger(__name__)


class ReportQueryService:
    """보고서 조회 서비스."""

    def get_reports(
        self,
        db: Session,
        report_type: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        search: Optional[str] = None,
        sort_by: str = "generated_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> ReportList:
        """보고서 목록 조회.

        Args:
            db: DB 세션
            report_type: 보고서 타입 필터
            period_start: 기간 시작 필터 (이후)
            period_end: 기간 종료 필터 (이전)
            search: 제목/요약 검색
            sort_by: 정렬 기준 (generated_at, period_end)
            sort_order: 정렬 순서 (asc, desc)
            page: 페이지 번호
            page_size: 페이지 크기

        Returns:
            ReportList
        """
        query = db.query(GeneratedReport).filter(GeneratedReport.deleted_at.is_(None))

        # 필터링
        if report_type:
            query = query.filter(GeneratedReport.report_type == report_type)

        if period_start:
            query = query.filter(GeneratedReport.period_end >= period_start)

        if period_end:
            query = query.filter(GeneratedReport.period_end <= period_end)

        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                (GeneratedReport.title.like(search_filter))
                | (GeneratedReport.summary.like(search_filter))
            )

        # 전체 개수
        total = query.count()

        # 정렬
        if sort_by == "period_end":
            order_column = GeneratedReport.period_end
        else:  # generated_at
            order_column = GeneratedReport.generated_at

        if sort_order == "asc":
            query = query.order_by(asc(order_column))
        else:
            query = query.order_by(desc(order_column))

        # 페이지네이션
        offset = (page - 1) * page_size
        items = query.offset(offset).limit(page_size).all()

        return ReportList(
            items=[self._to_list_item(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size,
        )

    def get_report(self, db: Session, report_id: int) -> Optional[ReportResponse]:
        """보고서 상세 조회."""
        report = (
            db.query(GeneratedReport)
            .filter(
                GeneratedReport.id == report_id, GeneratedReport.deleted_at.is_(None)
            )
            .first()
        )

        if not report:
            return None

        return self._to_response(report)

    def delete_report(self, db: Session, report_id: int) -> bool:
        """보고서 삭제 (soft delete).

        Returns:
            bool: 성공 여부
        """
        report = (
            db.query(GeneratedReport)
            .filter(
                GeneratedReport.id == report_id, GeneratedReport.deleted_at.is_(None)
            )
            .first()
        )

        if not report:
            return False

        report.deleted_at = datetime.now()
        db.commit()

        logger.info(f"Report {report_id} soft deleted")
        return True

    def _to_list_item(self, report: GeneratedReport) -> ReportListItem:
        """GeneratedReport를 ReportListItem으로 변환."""
        return ReportListItem(
            id=report.id,
            report_type=report.report_type,
            period_start=report.period_start,
            period_end=report.period_end,
            title=report.title,
            summary=report.summary,
            generated_at=report.generated_at,
            format=report.format,
        )

    def _to_response(self, report: GeneratedReport) -> ReportResponse:
        """GeneratedReport를 ReportResponse로 변환."""
        return ReportResponse(
            id=report.id,
            report_type=report.report_type,
            period_start=report.period_start,
            period_end=report.period_end,
            title=report.title,
            content=report.content,
            summary=report.summary,
            statistics=report.statistics,
            llm_request_id=report.llm_request_id,
            schedule_run_id=report.schedule_run_id,
            generated_at=report.generated_at,
            format=report.format,
        )


# 싱글톤 인스턴스
report_query_service = ReportQueryService()
