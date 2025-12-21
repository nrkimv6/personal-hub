"""LLM Request Models - 범용 LLM 요청 모델."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class LLMRequest(Base):
    """범용 LLM 요청 모델."""

    __tablename__ = "llm_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 호출자 식별
    caller_type = Column(String(50), nullable=False, index=True)  # 'instagram', 'naver', etc.
    caller_id = Column(String(100), nullable=False)  # 호출자 측 ID

    # 요청 정보
    prompt = Column(Text, nullable=False)
    requested_at = Column(DateTime, default=datetime.now, index=True)

    # 처리 상태
    status = Column(
        String(20), default="pending", nullable=False, index=True
    )  # pending/processing/completed/failed
    processed_at = Column(DateTime)

    # 결과
    result = Column(Text)  # JSON 응답
    raw_response = Column(Text)  # Claude 원본 응답
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<LLMRequest(id={self.id}, caller={self.caller_type}:{self.caller_id}, status={self.status})>"


class LLMWorkerStatus(Base):
    """LLM 워커 상태 모델."""

    __tablename__ = "llm_worker_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    worker_id = Column(String, unique=True, nullable=False)
    pid = Column(Integer)
    started_at = Column(DateTime, default=datetime.now)
    last_heartbeat = Column(DateTime)
    current_state = Column(String(20), default="idle")  # idle/processing/stopped
    current_request_id = Column(
        Integer,
        ForeignKey("llm_requests.id", ondelete="SET NULL"),
    )
    is_alive = Column(Boolean, default=True, index=True)
    processed_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)

    # Relationships
    current_request = relationship("LLMRequest")

    def __repr__(self) -> str:
        return f"<LLMWorkerStatus(worker_id={self.worker_id}, state={self.current_state})>"
