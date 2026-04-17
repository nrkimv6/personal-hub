"""WritingBatch Model - 글쓰기 배치 모델."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base


class WritingBatch(Base):
    """글쓰기 배치 모델.

    11개 LLM 요청 그룹(배치)을 추적합니다.
    """

    __tablename__ = "writing_batches"

    # 상태 상수
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_run_id = Column(
        Integer,
        ForeignKey("task_schedule_runs.id", ondelete="SET NULL"),
    )

    # 진행 상태
    status = Column(String(20), default=STATUS_PENDING, nullable=False, index=True)
    total_count = Column(Integer, default=11)
    completed_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)

    # 슬롯 컨텍스트 (JSON) - 당일 중복 방지용
    slot_context = Column(Text)

    # 시간
    created_at = Column(DateTime, default=datetime.now, index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # Relationships
    schedule_run = relationship("TaskScheduleRun", backref="writing_batches")

    def __repr__(self) -> str:
        completed = self.completed_count or 0
        total = self.total_count or 0
        return f"<WritingBatch(id={self.id}, status={self.status}, {completed}/{total})>"

    def mark_started(self):
        """배치 시작 표시."""
        self.status = self.STATUS_RUNNING
        self.started_at = datetime.now()

    def mark_completed(self):
        """배치 완료 표시."""
        self.status = self.STATUS_COMPLETED
        self.completed_at = datetime.now()

    def mark_failed(self):
        """배치 실패 표시."""
        self.status = self.STATUS_FAILED
        self.completed_at = datetime.now()

    def increment_completed(self):
        """완료 카운트 증가."""
        self.completed_count = (self.completed_count or 0) + 1
        self._check_completion()

    def increment_failed(self):
        """실패 카운트 증가."""
        self.failed_count = (self.failed_count or 0) + 1
        self._check_completion()

    def _check_completion(self):
        """완료 여부 체크."""
        completed = self.completed_count or 0
        failed = self.failed_count or 0
        total = self.total_count or 0
        if total and completed + failed >= total:
            self.mark_completed()

    @property
    def is_done(self) -> bool:
        """완료 여부."""
        return self.status in (self.STATUS_COMPLETED, self.STATUS_FAILED)

    @property
    def progress_percent(self) -> int:
        """진행률 (%)."""
        total = self.total_count or 0
        if total == 0:
            return 100
        completed = self.completed_count or 0
        failed = self.failed_count or 0
        return int((completed + failed) / total * 100)
