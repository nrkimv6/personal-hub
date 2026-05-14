"""GeneratedReport SQLAlchemy Model - LLM 생성 보고서."""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.base import Base


class GeneratedReport(Base):
    """LLM이 생성한 보고서 모델."""

    __tablename__ = "generated_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 보고서 타입
    report_type = Column(String(50), nullable=False, index=True)
    # nightly_cleanup, sleep_now, daily_summary, writing_report, crawl_report, custom

    # 기간 설정
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False, index=True)

    # 내용
    title = Column(String(200), nullable=True)
    content = Column(Text, nullable=False)  # Markdown/HTML
    summary = Column(Text, nullable=True)   # 한줄 요약

    # 통계 (JSON)
    statistics = Column(Text, nullable=True)
    # {"total_tasks": 15, "success_rate": 93.3, ...}

    # LLM 요청 연결
    llm_request_id = Column(Integer, ForeignKey("llm_requests.id", ondelete="SET NULL"), nullable=True)

    # 스케줄 연결
    schedule_run_id = Column(Integer, ForeignKey("task_schedule_runs.id"), nullable=True)

    # 메타데이터
    generated_at = Column(DateTime, default=datetime.now, index=True)
    format = Column(String(20), default="markdown")  # markdown, html

    # Soft delete
    deleted_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<GeneratedReport(id={self.id}, type={self.report_type}, generated_at={self.generated_at})>"
