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

    # 요청자 정보
    requested_by = Column(String(100), default="unknown")  # 'api', 'scheduler', 'manual', 'user:xxx'
    request_source = Column(String(100))  # 'instagram_crawl', 'manual_test', etc.
    provider = Column(String(20), default="claude")  # 'claude', 'gemini', etc.
    model = Column(String(100), default="")  # 모델명, 빈 문자열이면 Provider 기본 모델 사용

    # 처리 상태
    status = Column(
        String(20), default="pending", nullable=False, index=True
    )  # pending/processing/completed/failed/cancelled
    processed_at = Column(DateTime)

    # 결과
    result = Column(Text)  # JSON 응답
    raw_response = Column(Text)  # Claude 원본 응답
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)

    # CLI 옵션 (JSON) — caller별 CLI 파라미터 유연 전달
    cli_options = Column(Text)  # JSON: output_format, json_schema, allowed_tools, use_prompt_flag

    # 큐 구분 — 'utility'(기존 자동화 기본값) / 'system'(시스템/개발 우선순위 높음)
    queue_name = Column(String(30), default="utility", nullable=False, index=True)

    # Chat 모드 관련
    mode = Column(String(20), default="single", nullable=False)
    # "single": 기존 claude -p 방식 (결과 대기 후 반환)
    # "chat": 채팅형 세션 (스트리밍 출력)
    chat_session_id = Column(String(100), nullable=True)
    # chat 모드에서 세션 식별자 (Redis Pub/Sub 채널명: llm-chat:stream:{request_id})
    stream_log_path = Column(String(500), nullable=True)
    # chat 모드에서 스트리밍 로그 파일 경로

    # Claude 세션 ID — CLI stdout JSON의 session_id (JSONL 파일명 UUID와 동일)
    claude_session_id = Column(String(36), nullable=True, index=True)

    # Soft delete
    deleted_at = Column(DateTime)

    # 글쓰기 배치 관련
    writing_batch_id = Column(Integer, ForeignKey("writing_batches.id", ondelete="SET NULL"))
    writing_metadata = Column(Text)  # JSON: task_type, source_ids, selected_elements 등

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

    # Quota pause 상태
    quota_paused_provider = Column(String(50))  # 'gemini', 'claude' 등
    quota_paused_until = Column(DateTime)
    quota_pause_reason = Column(Text)

    # Relationships
    current_request = relationship("LLMRequest")

    def __repr__(self) -> str:
        return f"<LLMWorkerStatus(worker_id={self.worker_id}, state={self.current_state})>"
