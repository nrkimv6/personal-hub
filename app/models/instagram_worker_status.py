"""Instagram Worker Status SQLAlchemy Model."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from datetime import datetime

from .base import Base


class InstagramWorkerStatus(Base):
    """Instagram 워커 상태 추적 모델."""
    __tablename__ = "instagram_worker_status"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 워커 식별
    worker_id = Column(String(36), unique=True, nullable=False, index=True)  # UUID
    pid = Column(Integer, nullable=True)  # 프로세스 ID

    # 시간 정보
    started_at = Column(DateTime, nullable=False)
    last_heartbeat = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now)

    # 상태 정보
    current_state = Column(String(20), default="idle")  # idle, crawling, processing
    current_account = Column(String(100), nullable=True)
    current_run_id = Column(Integer, ForeignKey("task_schedule_runs.id", ondelete="SET NULL"), nullable=True)

    # 활성 여부
    is_alive = Column(Boolean, default=True, index=True)

    def __repr__(self):
        return f"<InstagramWorkerStatus(id={self.id}, worker_id={self.worker_id}, state={self.current_state}, alive={self.is_alive})>"
