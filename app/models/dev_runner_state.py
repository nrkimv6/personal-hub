"""Dev Runner Postgres mirror models."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base


class DevRunnerState(Base):
    """Persistent mirror of per-runner Redis metadata."""

    __tablename__ = "dev_runner_state"

    runner_id = Column(String(64), primary_key=True)
    plan_file = Column(String, nullable=False)
    project = Column(String(100), nullable=False, default="monitor-page")
    status = Column(String(50), nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    branch = Column(String, nullable=True)
    worktree_path = Column(String, nullable=True)
    exit_reason = Column(String(100), nullable=True)
    merge_requested = Column(Boolean, nullable=False, default=False)
    completed_at = Column(DateTime, nullable=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)

    merge_requests = relationship("DevRunnerMergeRequest", back_populates="runner_state")

    __table_args__ = (
        CheckConstraint(
            "status NOT IN ('머지대기', '통합테스트중') OR branch IS NOT NULL",
            name="ck_dev_runner_state_branch_required_for_merge_status",
        ),
        Index("idx_dev_runner_state_status", "status"),
        Index("idx_dev_runner_state_started_at", "started_at"),
    )


class DevRunnerMergeRequest(Base):
    """Persistent mirror of a merge queue item."""

    __tablename__ = "dev_runner_merge_request"

    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String(64), ForeignKey("dev_runner_state.runner_id", ondelete="CASCADE"), nullable=False)
    branch = Column(String, nullable=False)
    worktree_path = Column(String, nullable=False)
    plan_file = Column(String, nullable=False)
    project = Column(String(100), nullable=False, default="monitor-page")
    state = Column(String(30), nullable=False, default="pending")
    retry_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    claim_token = Column(String(128), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_detail = Column(Text, nullable=True)

    runner_state = relationship("DevRunnerState", back_populates="merge_requests")

    __table_args__ = (
        Index("idx_merge_request_state", "state"),
        Index("idx_merge_request_created_at", "created_at"),
        Index("idx_merge_request_runner_id", "runner_id"),
    )
