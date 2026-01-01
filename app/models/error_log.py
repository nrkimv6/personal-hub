"""
에러 로그 모델
시스템 전반의 에러를 중앙 집중 저장
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Index
from app.models.base import Base


class ErrorLog(Base):
    """에러 로그"""

    __tablename__ = "error_logs"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # 분류
    source = Column(String(50), nullable=False, index=True)  # api, worker, naver, instagram, writing
    severity = Column(String(20), nullable=False, index=True)  # critical, error, warning
    error_type = Column(String(100), nullable=False, index=True)  # 예외 클래스명

    # 상세 정보
    message = Column(Text, nullable=False)
    traceback = Column(Text)
    context = Column(JSON)  # 추가 컨텍스트 (schedule_id, account_id, url 등)

    # 해결 상태
    resolved = Column(Boolean, default=False, nullable=False, index=True)
    resolved_at = Column(DateTime)
    resolved_by = Column(String(100))  # 해결한 사용자/시스템
    notes = Column(Text)  # 해결 노트

    # 복합 인덱스
    __table_args__ = (
        Index("ix_error_logs_source_severity", "source", "severity"),
        Index("ix_error_logs_created_resolved", "created_at", "resolved"),
    )

    def __repr__(self):
        return f"<ErrorLog(id={self.id}, source={self.source}, severity={self.severity}, error_type={self.error_type})>"
