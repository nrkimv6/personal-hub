"""
Workflow 모델
dev-runner 브랜치/계획서/runner 상태를 하나의 엔티티로 통합 관리
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from app.models.base import Base


# 상태 상수
STATUS_PLANNED = "planned"
STATUS_RUNNING = "running"
STATUS_MERGE_PENDING = "merge_pending"
STATUS_MERGING = "merging"
STATUS_MERGED = "merged"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


class Workflow(Base):
    """워크플로우 — 브랜치 + 계획서 + runner 상태의 영속적 이력"""

    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String, unique=True, nullable=False)          # 고유 식별자 (e.g., "2026-03-03_workflow-manager")
    plan_file = Column(String, nullable=True)                   # 계획서 경로
    branch = Column(String, nullable=True)                      # git 브랜치
    runner_id = Column(String, nullable=True)                   # dev-runner ID
    status = Column(String, nullable=False, default=STATUS_PLANNED)
    engine = Column(String, nullable=True)                      # claude|gemini
    error_message = Column(Text, nullable=True)
    commit_hash = Column(String, nullable=True)                 # 머지 커밋 해시
    worktree_path = Column(String, nullable=True)               # 활성 worktree 경로
    created_at = Column(DateTime, default=datetime.now)
    started_at = Column(DateTime, nullable=True)
    merged_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_workflows_status", "status"),
        Index("ix_workflows_slug", "slug"),
        Index("ix_workflows_created_at", "created_at"),
    )

    def mark_running(self, runner_id: str, branch: str, worktree_path: str) -> None:
        """running 상태로 전이"""
        self.status = STATUS_RUNNING
        self.runner_id = runner_id
        self.branch = branch
        self.worktree_path = worktree_path
        self.started_at = datetime.now()

    def mark_merge_pending(self) -> None:
        """merge_pending 상태로 전이"""
        self.status = STATUS_MERGE_PENDING

    def mark_merged(self, commit_hash: str) -> None:
        """merged 상태로 전이"""
        self.status = STATUS_MERGED
        self.commit_hash = commit_hash
        self.merged_at = datetime.now()
        self.finished_at = datetime.now()

    def mark_failed(self, error_message: str) -> None:
        """failed 상태로 전이"""
        self.status = STATUS_FAILED
        self.error_message = error_message
        self.finished_at = datetime.now()

    def __repr__(self):
        return f"<Workflow(id={self.id}, slug={self.slug}, status={self.status})>"
