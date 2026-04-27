"""VideoDownload SQLAlchemy Model - 비디오 다운로드 요청."""

from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime

from .base import Base


class VideoDownload(Base):
    """비디오 다운로드 요청 모델.

    YouTube/Vimeo/Instagram Reel 등 비디오 다운로드 요청을 관리합니다.
    VideoDownloadWorker가 pending 상태의 요청을 처리합니다.
    """

    __tablename__ = "video_downloads"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 요청 정보
    url = Column(Text, nullable=False)
    download_type = Column(String(20), nullable=False, index=True)  # youtube, youtube_stream, vimeo, instagram

    # 상태
    # pending: 대기중
    # picked: 워커가 가져감
    # processing: 다운로드 진행중
    # completed: 완료
    # failed: 실패
    # cancelled: 취소됨
    status = Column(String(20), nullable=False, default="pending", index=True)

    # 옵션
    quality = Column(String(20), default="best")  # best, worst, 1080, 720 등
    embedding_url = Column(Text, nullable=True)  # Vimeo 도메인 제한 우회용
    output_filename = Column(String(255), nullable=True)  # 사용자 지정 파일명

    # 진행 상태
    progress = Column(Integer, default=0)  # 0-100
    output_path = Column(Text, nullable=True)  # 완료된 파일 경로
    file_size = Column(Integer, nullable=True)  # 파일 크기 (bytes)
    title = Column(String(500), nullable=True)  # 비디오 제목

    # 처리 정보
    picked_at = Column(DateTime, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    worker_id = Column(String(100), nullable=True)

    # 에러
    error_message = Column(Text, nullable=True)

    # 메타
    created_at = Column(DateTime, default=datetime.now)

    # 상태 상수
    STATUS_PENDING = "pending"
    STATUS_PICKED = "picked"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    # 다운로드 타입 상수
    TYPE_YOUTUBE = "youtube"
    TYPE_YOUTUBE_STREAM = "youtube_stream"
    TYPE_VIMEO = "vimeo"
    TYPE_INSTAGRAM = "instagram"

    def __repr__(self):
        return f"<VideoDownload(id={self.id}, type={self.download_type}, status={self.status})>"

    def mark_picked(self, worker_id: str):
        """워커가 요청을 가져감으로 표시."""
        self.status = self.STATUS_PICKED
        self.picked_at = datetime.now()
        self.worker_id = worker_id

    def mark_processing(self):
        """다운로드 진행 중으로 표시."""
        self.status = self.STATUS_PROCESSING

    def update_progress(self, progress: int):
        """진행률 업데이트."""
        self.progress = min(100, max(0, progress))

    def mark_completed(self, output_path: str, file_size: int = None, title: str = None):
        """완료로 표시."""
        self.status = self.STATUS_COMPLETED
        self.processed_at = datetime.now()
        self.output_path = output_path
        self.progress = 100
        if file_size:
            self.file_size = file_size
        if title:
            self.title = title

    def mark_failed(self, error_message: str):
        """실패로 표시."""
        self.status = self.STATUS_FAILED
        self.processed_at = datetime.now()
        self.error_message = error_message

    def mark_cancelled(self):
        """취소로 표시."""
        self.status = self.STATUS_CANCELLED
        self.processed_at = datetime.now()
