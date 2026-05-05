"""Plan Archive document patch proposal models."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text

from app.models.base import Base


class PlanArchiveDocPatchProposal(Base):
    """Preview/apply record for a controlled archive markdown patch."""

    __tablename__ = "plan_archive_doc_patch_proposals"
    __table_args__ = (
        Index("ix_plan_archive_doc_patch_proposals_status", "status"),
        Index("ix_plan_archive_doc_patch_proposals_record", "plan_record_id"),
        Index("ix_plan_archive_doc_patch_proposals_report", "insight_report_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_record_id = Column(Integer, ForeignKey("plan_records.id"), nullable=False, index=True)
    insight_report_id = Column(Integer, ForeignKey("plan_archive_insight_reports.id"), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="draft")
    target_path = Column(String(1000), nullable=False)
    patch_text = Column(Text, nullable=False, default="")
    preview_text = Column(Text, nullable=True)
    changed_lines_summary = Column(JSON, nullable=True)
    applied_commit = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    applied_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<PlanArchiveDocPatchProposal(id={self.id}, status={self.status})>"
