"""Instagram Crawl Request SQLAlchemy Model."""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class InstagramCrawlRequest(Base):
    """Instagram 크롤링 요청 모델 (수동 실행 큐)."""
    __tablename__ = "instagram_crawl_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 요청 정보
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    requested_at = Column(DateTime, default=datetime.now, index=True)
    requested_by = Column(String(20), default="manual")  # 'manual', 'scheduler', 'retry'

    # 요청 타입: 'feed' (피드 크롤링), 'single_post' (개별 게시물 재크롤링)
    request_type = Column(String(20), default="feed", nullable=False, index=True)
    # 재크롤링 대상 게시물 ID (single_post 타입일 때만 사용)
    target_post_id = Column(Integer, ForeignKey("instagram_posts.id", ondelete="SET NULL"), nullable=True)

    # 처리 상태
    status = Column(String(20), default="pending", index=True)  # 'pending', 'processing', 'completed', 'failed'
    processed_at = Column(DateTime)
    crawl_run_id = Column(Integer, ForeignKey("instagram_crawl_runs.id", ondelete="SET NULL"), nullable=True)

    # 오류 정보
    error_message = Column(Text)

    # Relationships
    target_post = relationship("InstagramPost", foreign_keys=[target_post_id])

    def __repr__(self):
        return f"<InstagramCrawlRequest(id={self.id}, account_id={self.account_id}, type={self.request_type}, status={self.status})>"
