"""
계획서 실행점유 레코드 모델

계획서 상태(status vocabulary)와 분리된 실행 점유 관리.
queued/active/released/stale은 plan 상태가 아니라 claim 상태다.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, JSON, Index, ForeignKey, UniqueConstraint
from app.models.base import Base


class PlanExecutionClaim(Base):
    """계획서 실행점유 — runner/session/pid/heartbeat를 DB 단일 source of truth로 관리"""

    __tablename__ = "plan_execution_claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(String(36), unique=True, nullable=False)  # UUID4, > 실행점유: 헤더 포인터

    # plan 식별 (plan_record_id는 PlanRecord가 없을 수 있으므로 nullable)
    plan_record_id = Column(Integer, ForeignKey("plan_records.id", ondelete="SET NULL"), nullable=True)
    plan_path = Column(String, nullable=False, index=True)

    # claim 상태: queued | active | released | stale
    state = Column(String(20), nullable=False, default="queued")

    # 실행 주체 관측 필드
    engine = Column(String(50), nullable=True)       # claude / codex / gemini
    session_id = Column(String(36), nullable=True)   # Claude session UUID
    runner_id = Column(String(36), nullable=True)    # dev-runner UUID
    pid = Column(Integer, nullable=True)             # 관측값 only, 식별자 아님
    host = Column(String(255), nullable=True)        # 실행 호스트명

    # worktree 관측 (activate_claim 시 기록)
    branch = Column(String, nullable=True)
    worktree_path = Column(String, nullable=True)

    # 시간 계약
    claimed_at = Column(DateTime, nullable=False, default=datetime.now)
    heartbeat_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)
    queue_after = Column(DateTime, nullable=True)    # queued 상태에서 처리 가능한 최소 시각

    claim_metadata = Column(JSON, nullable=True)     # 추가 맥락 (plan 제목, 큐 순서 등)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("ix_plan_execution_claims_plan_path_state", "plan_path", "state"),
        Index("ix_plan_execution_claims_state", "state"),
        Index("ix_plan_execution_claims_runner_id", "runner_id"),
    )

    def __repr__(self):
        return f"<PlanExecutionClaim(claim_id={self.claim_id[:8]}..., state={self.state}, plan_path={self.plan_path})>"
