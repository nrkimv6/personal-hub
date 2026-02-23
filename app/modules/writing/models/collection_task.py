"""CollectionTask Model - Writing 수집 작업 비동기 상태 추적 모델."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class CollectionTask(Base):
    """Writing 수집 작업 상태 추적 모델.

    feeds_collect, search_queries_collect, wikisource_collect 등
    오래 걸리는 수집 작업을 비동기로 실행할 때 상태를 추적합니다.
    """

    __tablename__ = "writing_collection_tasks"

    # 타입 상수
    TYPE_FEEDS = "feeds_collect"
    TYPE_SEARCH_QUERIES = "search_queries_collect"
    TYPE_WIKISOURCE = "wikisource_collect"

    # 상태 상수
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    task_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default=STATUS_PENDING, index=True)

    # 진행 상황 JSON: {"collected": 12, "total": 50, "current_source": "..."}
    progress_json = Column(Text)

    # 결과 요약 JSON: {"collected_count": 50, "skipped": 3, "sources": [...]}
    result_json = Column(Text)

    # 오류 메시지 (실패 시)
    error_message = Column(Text)

    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    def __repr__(self) -> str:
        return f"<CollectionTask(task_id={self.task_id}, type={self.type}, status={self.status})>"

    def mark_started(self):
        """작업 시작 표시."""
        self.status = self.STATUS_RUNNING
        self.started_at = datetime.now()

    def mark_completed(self, result_json: Optional[str] = None):
        """작업 완료 표시."""
        self.status = self.STATUS_COMPLETED
        self.completed_at = datetime.now()
        if result_json is not None:
            self.result_json = result_json

    def mark_failed(self, error_message: Optional[str] = None):
        """작업 실패 표시."""
        self.status = self.STATUS_FAILED
        self.completed_at = datetime.now()
        if error_message is not None:
            self.error_message = error_message

    @property
    def is_done(self) -> bool:
        """완료 여부 (성공 또는 실패)."""
        return self.status in (self.STATUS_COMPLETED, self.STATUS_FAILED)
