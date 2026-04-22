"""MP4 -> GIF asynchronous conversion task model."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from .base import Base


class Mp4GifTask(Base):
    """Track one uploaded MP4 -> GIF conversion request."""

    __tablename__ = "mp4_gif_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(36), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="queued", index=True)

    source_name = Column(String(255), nullable=False)
    stored_input_path = Column(Text, nullable=False)
    stored_output_path = Column(Text, nullable=False)
    fps = Column(Integer, nullable=False, default=10)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.now)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    def mark_running(self) -> None:
        self.status = self.STATUS_RUNNING
        self.started_at = datetime.now()
        self.error_message = None

    def mark_completed(self) -> None:
        self.status = self.STATUS_COMPLETED
        self.completed_at = datetime.now()
        self.error_message = None

    def mark_failed(self, message: str) -> None:
        self.status = self.STATUS_FAILED
        self.completed_at = datetime.now()
        self.error_message = message
