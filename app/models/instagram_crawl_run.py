"""Instagram Crawl Run SQLAlchemy Model."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class InstagramCrawlRun(Base):
    """Instagram 크롤링 실행 기록 모델."""
    __tablename__ = "instagram_crawl_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 실행 정보
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    finished_at = Column(DateTime)

    # 결과
    success = Column(Boolean, default=False)
    total_collected = Column(Integer, default=0)
    new_saved = Column(Integer, default=0)
    error_message = Column(Text)

    # 관계
    posts = relationship("InstagramPost", back_populates="crawl_run")

    def __repr__(self):
        return f"<InstagramCrawlRun(id={self.id}, account_id={self.account_id}, success={self.success})>"
