"""FileSearchRequest SQLAlchemy Model - 파일 검색 비동기 요청."""

from sqlalchemy import Column, Integer, String, Text
from datetime import datetime

from .base import Base


class FileSearchRequest(Base):
    """파일 검색 비동기 요청 모델.

    API(Session 0) → Redis 큐 → FileSearchWorker(유저 세션) 패턴에서
    검색 요청 상태를 추적하는 테이블.
    """

    __tablename__ = "file_search_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    search_id = Column(String(36), nullable=False, unique=True, index=True)  # UUID

    # 상태
    # pending: DB에 저장됨, Redis 미발행 또는 발행 전
    # queued: Redis 큐에 들어감
    # processing: 워커가 처리 중
    # completed: 완료
    # failed: 실패
    status = Column(String(20), nullable=False, default="pending", index=True)

    # 요청/결과 직렬화 (JSON)
    request_json = Column(Text, nullable=False)
    result_json = Column(Text, nullable=True)

    # 에러 메시지
    error_message = Column(Text, nullable=True)

    # 타임스탬프
    created_at = Column(String(30), nullable=False, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    completed_at = Column(String(30), nullable=True)
    search_time_ms = Column(Integer, nullable=True)

    # 상태 상수
    STATUS_PENDING = "pending"
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    def __repr__(self):
        return f"<FileSearchRequest(search_id={self.search_id}, status={self.status})>"

    def mark_processing(self):
        """워커가 처리 시작으로 표시."""
        self.status = self.STATUS_PROCESSING

    def mark_completed(self, result_json: str, search_time_ms: int):
        """검색 완료로 표시."""
        self.status = self.STATUS_COMPLETED
        self.result_json = result_json
        self.search_time_ms = search_time_ms
        self.completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def mark_failed(self, error_message: str):
        """실패로 표시."""
        self.status = self.STATUS_FAILED
        self.error_message = error_message
        self.completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
