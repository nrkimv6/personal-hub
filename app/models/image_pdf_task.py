"""Image -> PDF asynchronous conversion task model."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from .base import Base


class ImagePdfTask(Base):
    """Track one uploaded image -> PDF conversion request."""

    __tablename__ = "image_pdf_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(36), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="queued", index=True)

    source_names = Column(Text, nullable=False)
    file_count = Column(Integer, nullable=False, default=0)
    stored_input_dir = Column(Text, nullable=False)
    stored_output_path = Column(Text, nullable=False)
    bw = Column(Boolean, nullable=False, default=False)
    white = Column(Integer, nullable=False, default=200)
    black = Column(Integer, nullable=False, default=80)
    quality = Column(Integer, nullable=False, default=85)
    preserve_dpi = Column(Boolean, nullable=False, default=False)
    download_filename = Column(String(255), nullable=True)
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
