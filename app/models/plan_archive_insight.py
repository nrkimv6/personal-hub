"""Plan Archive insight report models."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint

from app.models.base import Base


class PlanArchiveInsightReport(Base):
    """LLM-generated report over deterministic plan archive metrics."""

    __tablename__ = "plan_archive_insight_reports"
    __table_args__ = (
        UniqueConstraint(
            "range_start",
            "range_end",
            "grouping",
            "provider",
            "model",
            "metrics_hash",
            name="uq_plan_archive_insight_report_scope",
        ),
        Index("ix_plan_archive_insight_reports_status", "status"),
        Index("ix_plan_archive_insight_reports_range", "range_start", "range_end"),
        Index("ix_plan_archive_insight_reports_grouping", "grouping"),
        Index("ix_plan_archive_insight_reports_llm_request", "llm_request_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    range_start = Column(DateTime, nullable=True)
    range_end = Column(DateTime, nullable=True)
    grouping = Column(String(100), nullable=False, default="category")
    metrics_hash = Column(String(64), nullable=False)
    metrics_json = Column(JSON, nullable=True)
    evidence_json = Column(JSON, nullable=True)
    insight_json = Column(JSON, nullable=True)
    raw_response = Column(Text, nullable=True)
    provider = Column(String(50), nullable=False, default="claude")
    model = Column(String(100), nullable=False, default="")
    status = Column(String(30), nullable=False, default="pending")
    warning = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    llm_request_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<PlanArchiveInsightReport(id={self.id}, status={self.status}, grouping={self.grouping})>"
