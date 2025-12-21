"""Instagram LLM Classification Models."""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class InstagramLLMClassificationRequest(Base):
    """Instagram LLM 분류 요청 모델."""

    __tablename__ = "instagram_llm_classification_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(
        Integer,
        ForeignKey("instagram_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 요청 정보
    requested_at = Column(DateTime, default=datetime.now, index=True)
    requested_by = Column(String(20), default="auto")  # 'auto', 'manual'
    trigger_tag = Column(String(50))  # LLM 분류를 트리거한 태그

    # 처리 상태
    status = Column(
        String(20), default="pending", nullable=False, index=True
    )  # 'pending', 'processing', 'completed', 'failed'
    processed_at = Column(DateTime)

    # LLM 결과
    llm_result = Column(Text)  # JSON 형식
    confidence_score = Column(Float)  # 0.0 ~ 1.0

    # 에러 정보
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)

    # 프롬프트/응답 로깅
    prompt_used = Column(Text)
    raw_response = Column(Text)

    # Relationships
    post = relationship("InstagramPost", back_populates="llm_requests")

    def __repr__(self) -> str:
        return f"<InstagramLLMRequest(id={self.id}, post_id={self.post_id}, status={self.status})>"


class InstagramLLMWorkerStatus(Base):
    """Instagram LLM 워커 상태 모델."""

    __tablename__ = "instagram_llm_worker_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    worker_id = Column(String, unique=True, nullable=False)
    pid = Column(Integer)
    started_at = Column(DateTime, nullable=False)
    last_heartbeat = Column(DateTime, nullable=False)
    current_state = Column(String(20), default="idle")  # 'idle', 'processing', 'stopped'
    current_request_id = Column(
        Integer,
        ForeignKey("instagram_llm_classification_requests.id", ondelete="SET NULL"),
    )
    is_alive = Column(Boolean, default=True, index=True)
    processed_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)

    # Relationships
    current_request = relationship("InstagramLLMClassificationRequest")

    def __repr__(self) -> str:
        return f"<InstagramLLMWorkerStatus(worker_id={self.worker_id}, state={self.current_state})>"
