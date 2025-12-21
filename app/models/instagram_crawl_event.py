"""Instagram Crawl Event SQLAlchemy Model."""

from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship

from .base import Base


class InstagramCrawlEvent(Base):
    """Instagram 크롤링 이벤트 로그 모델.

    크롤링 실행 중 발생하는 이벤트를 기록합니다.
    """
    __tablename__ = "instagram_crawl_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    crawl_run_id = Column(Integer, ForeignKey("instagram_crawl_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(String(50), nullable=False, index=True)  # ISO format
    event_type = Column(String(30), nullable=False, index=True)  # 'scroll', 'post_saved', 'duplicate', 'refresh', 'stop'
    message = Column(Text, nullable=True)
    details = Column(Text, nullable=True)  # JSON

    def __repr__(self):
        return f"<InstagramCrawlEvent(id={self.id}, type={self.event_type}, msg={self.message[:30] if self.message else None})>"
