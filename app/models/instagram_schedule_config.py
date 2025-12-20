"""Instagram Schedule Config SQLAlchemy Model."""

from sqlalchemy import Column, Integer, DateTime, Boolean, JSON
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

    # 메타
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<InstagramScheduleConfig(id={self.id}, enabled={self.enabled})>"
