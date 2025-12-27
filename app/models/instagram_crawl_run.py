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
    service_account_id = Column(Integer, ForeignKey("service_accounts.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime, default=datetime.now, index=True)
    finished_at = Column(DateTime)

    # 결과
    success = Column(Boolean, default=False)
    total_collected = Column(Integer, default=0)
    new_saved = Column(Integer, default=0)
    error_message = Column(Text)

    # 재시도 정보 (2025-12-21 추가)
    retry_count = Column(Integer, default=0)
    retry_of_run_id = Column(Integer, ForeignKey("instagram_crawl_runs.id"), nullable=True)
    failure_reason = Column(String(50), nullable=True)  # 'login_required', 'network_error', 'timeout', 'rate_limit', 'unknown'

    # 크롤링 상세 정보 (2025-12-21 추가)
    stop_reason = Column(String(50), nullable=True)  # 'max_posts_reached', 'duplicate_stop', 'max_refresh_after_duplicates', etc.
    duplicate_count = Column(Integer, default=0)  # 중단 시점의 연속 중복 개수
    scroll_performed = Column(Integer, default=0)  # 실제 수행된 스크롤 횟수
    refresh_count = Column(Integer, default=0)  # 새로고침 횟수
    config_snapshot = Column(Text, nullable=True)  # 수집 시점의 설정값 JSON

    # 관계
    posts = relationship("InstagramPost", back_populates="crawl_run")

    def __repr__(self):
        return f"<InstagramCrawlRun(id={self.id}, service_account_id={self.service_account_id}, success={self.success}, stop_reason={self.stop_reason})>"
