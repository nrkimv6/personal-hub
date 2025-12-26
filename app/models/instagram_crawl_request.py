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
    service_account_id = Column(Integer, ForeignKey("service_accounts.id", ondelete="CASCADE"), nullable=False)
    requested_at = Column(DateTime, default=datetime.now, index=True)
    requested_by = Column(String(20), default="manual")  # 'manual', 'scheduler', 'retry'

    # 요청 타입: 'feed' (피드 크롤링), 'single_post' (개별 게시물 재크롤링), 'single_post_url' (URL로 단일 게시물 수집)
    request_type = Column(String(20), default="feed", nullable=False, index=True)
    # 재크롤링 대상 게시물 ID (single_post 타입일 때만 사용)
    target_post_id = Column(Integer, ForeignKey("instagram_posts.id", ondelete="SET NULL"), nullable=True)
    # 크롤링 대상 URL (single_post_url 타입일 때 사용)
    target_url = Column(String(500), nullable=True)
    # URL 타입 (URL 기반 크롤링 시): main_feed, account_profile, account_reels, single_post, single_reel, reels_explore, hashtag
    url_type = Column(String(50), nullable=True, index=True)

    # 처리 상태
    status = Column(String(20), default="pending", index=True)  # 'pending', 'processing', 'completed', 'failed'
    processed_at = Column(DateTime)
    crawl_run_id = Column(Integer, ForeignKey("instagram_crawl_runs.id", ondelete="SET NULL"), nullable=True)

    # 오류 정보
    error_message = Column(Text)

    # Relationships
    service_account = relationship("ServiceAccount", backref="crawl_requests")
    target_post = relationship("InstagramPost", foreign_keys=[target_post_id])

    def __repr__(self):
        return f"<InstagramCrawlRequest(id={self.id}, service_account_id={self.service_account_id}, type={self.request_type}, status={self.status})>"
