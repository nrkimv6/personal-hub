"""Instagram Schedule Config SQLAlchemy Model."""

from sqlalchemy import Column, Integer, DateTime, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class InstagramScheduleConfig(Base):
    """Instagram 스케줄 설정 모델."""
    __tablename__ = "instagram_schedule_config"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 설정
    enabled = Column(Boolean, default=True)
    daily_runs = Column(Integer, default=3)
    time_windows = Column(JSON, default=lambda: [
        {"start": "07:00", "end": "10:00"},
        {"start": "12:00", "end": "15:00"},
        {"start": "19:00", "end": "23:00"},
    ])
    max_posts = Column(Integer, default=20)
    scroll_count = Column(Integer, default=3)

    # 고급 설정 (2025-12-21 추가)
    min_interval_hours = Column(Integer, default=2)  # 최소 실행 간격
    duplicate_stop_count = Column(Integer, default=5)  # 연속 중복 시 중단

    # 재시도 설정
    max_retries = Column(Integer, default=3)
    retry_interval_minutes = Column(Integer, default=5)

    # 계정 지정 (2025-12-21 추가)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    account = relationship("Account")

    # 메타
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<InstagramScheduleConfig(id={self.id}, enabled={self.enabled})>"
