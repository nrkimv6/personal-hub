"""Crawl Request SQLAlchemy Model - 단건 크롤링 요청."""

from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class CrawlRequest(Base):
    """단건 크롤링 요청 모델."""

    __tablename__ = "crawl_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 요청 정보
    url = Column(Text, nullable=False)
    url_type = Column(String(50), nullable=False, index=True)  # 'instagram', 'naver_blog', 'google_form', ...

    # 상태 (워커 실행 시도 포함)
    # pending: 대기중
    # picked: 워커가 가져감
    # processing: 크롤링 진행중
    # completed: 완료
    # failed: 실패
    status = Column(String(20), nullable=False, default="pending", index=True)

    # 요청 출처
    requested_by = Column(String(20), default="manual")  # 'manual', 'api', 'retry'
    requested_at = Column(DateTime, default=datetime.now, index=True)

    # 처리 정보
    picked_at = Column(DateTime, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    worker_id = Column(String(100), nullable=True)  # 처리한 워커 ID

    # 결과 연결 (다형성)
    result_type = Column(String(50), nullable=True)  # 'instagram_post', 'crawled_page'
    result_id = Column(Integer, nullable=True)

    # 에러
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)

    # 메타
    created_at = Column(DateTime, default=datetime.now)

    # 상태 상수
    STATUS_PENDING = "pending"
    STATUS_PICKED = "picked"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    # URL 타입 상수
    URL_TYPE_INSTAGRAM = "instagram"
    URL_TYPE_NAVER_BLOG = "naver_blog"
    URL_TYPE_NAVER_FORM = "naver_form"
    URL_TYPE_GOOGLE_FORM = "google_form"
    URL_TYPE_OTHER = "other"

    def __repr__(self):
        return f"<CrawlRequest(id={self.id}, url_type={self.url_type}, status={self.status})>"

    def mark_picked(self, worker_id: str):
        """워커가 요청을 가져감으로 표시."""
        self.status = self.STATUS_PICKED
        self.picked_at = datetime.now()
        self.worker_id = worker_id

    def mark_processing(self):
        """크롤링 진행 중으로 표시."""
        self.status = self.STATUS_PROCESSING

    def mark_completed(self, result_type: str, result_id: int):
        """완료로 표시."""
        self.status = self.STATUS_COMPLETED
        self.processed_at = datetime.now()
        self.result_type = result_type
        self.result_id = result_id

    def mark_failed(self, error_message: str):
        """실패로 표시."""
        self.status = self.STATUS_FAILED
        self.processed_at = datetime.now()
        self.error_message = error_message
