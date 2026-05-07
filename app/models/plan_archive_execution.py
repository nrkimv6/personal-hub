"""Plan Archive execution job/attempt read models."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base
from app.modules.claude_worker.models import llm_request as _llm_request  # noqa: F401


class PlanArchiveExecutionJob(Base):
    """One archive-analysis execution job for a PlanRecord."""

    __tablename__ = "plan_archive_execution_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_record_id = Column(Integer, ForeignKey("plan_records.id", ondelete="CASCADE"), nullable=False)
    trigger_source = Column(String(100), nullable=False)
    status = Column(String(30), nullable=False, default="pending", index=True)
    selected_profiles = Column(JSON, nullable=True)
    profile_count = Column(Integer, nullable=False, default=0)
    latest_request_id = Column(Integer, ForeignKey("llm_requests.id", ondelete="SET NULL"), nullable=True)
    next_available_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    queued_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    record = relationship("PlanRecord")
    latest_request = relationship("LLMRequest", foreign_keys=[latest_request_id])
    attempts = relationship(
        "PlanArchiveExecutionAttempt",
        back_populates="job",
        order_by="PlanArchiveExecutionAttempt.created_at",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_plan_archive_execution_jobs_record", "plan_record_id"),
        Index("ix_plan_archive_execution_jobs_trigger", "trigger_source"),
        Index("ix_plan_archive_execution_jobs_latest_request", "latest_request_id"),
    )


class PlanArchiveExecutionAttempt(Base):
    """One LLMRequest attempt attached to a Plan Archive execution job."""

    __tablename__ = "plan_archive_execution_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("plan_archive_execution_jobs.id", ondelete="CASCADE"), nullable=False)
    llm_request_id = Column(Integer, ForeignKey("llm_requests.id", ondelete="SET NULL"), nullable=True)
    attempt_index = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False, default="queued", index=True)
    engine = Column(String(50), nullable=True)
    profile_name = Column(String(100), nullable=True)
    provider = Column(String(50), nullable=True)
    model = Column(String(100), nullable=True)
    retryable = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    requested_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    job = relationship("PlanArchiveExecutionJob", back_populates="attempts")
    request = relationship("LLMRequest")

    __table_args__ = (
        UniqueConstraint("llm_request_id", name="uq_plan_archive_execution_attempt_request"),
        Index("ix_plan_archive_execution_attempts_job", "job_id"),
        Index("ix_plan_archive_execution_attempts_request", "llm_request_id"),
        Index("ix_plan_archive_execution_attempts_profile", "engine", "profile_name"),
    )
