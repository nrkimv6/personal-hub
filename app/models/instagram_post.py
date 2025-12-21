"""Instagram Post SQLAlchemy Model."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class InstagramPost(Base):
    """Instagram 게시물 모델."""
    __tablename__ = "instagram_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 기본 정보
    post_id = Column(String, unique=True, nullable=False, index=True)
    account = Column(String, nullable=False, index=True)
    url = Column(String)

    # 콘텐츠
    caption = Column(Text)
    images = Column(JSON, default=list)  # [{"src": "...", "alt": "..."}]

    # 메타데이터
    posted_at = Column(DateTime, index=True)
    display_time = Column(String)
    is_ad = Column(Boolean, default=False)

    # 수집 정보
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"))
    crawl_run_id = Column(Integer, ForeignKey("instagram_crawl_runs.id", ondelete="SET NULL"))
    collected_at = Column(DateTime, default=datetime.now, index=True)

    # 관계
    crawl_run = relationship("InstagramCrawlRun", back_populates="posts")

    def __repr__(self):
        return f"<InstagramPost(id={self.id}, post_id={self.post_id}, account={self.account})>"
