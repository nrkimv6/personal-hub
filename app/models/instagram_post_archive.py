"""Instagram Post Archive SQLAlchemy Model (read-only)."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class InstagramPostArchive(Base):
    """Instagram 게시물 아카이브 모델 (read-only).

    instagram_posts_archive 파티셔닝 부모 테이블 매핑.
    관계(relationship) 없음 — 조회 전용.
    """
    __tablename__ = "instagram_posts_archive"

    id = Column(Integer, primary_key=True)
    post_id = Column(String, nullable=False, index=True)
    account = Column(String, nullable=False, index=True)
    url = Column(String)

    caption = Column(Text)
    images = Column(JSON)

    posted_at = Column(DateTime, index=True)
    display_time = Column(String)
    is_ad = Column(Boolean, default=False)
    post_type = Column(String, default="NORMAL", index=True)
    likes = Column(Integer)
    comments = Column(Integer)

    is_reel = Column(Boolean, default=False)
    duration = Column(Float)
    music_title = Column(Text)
    music_artist = Column(Text)

    service_account_id = Column(Integer)
    crawl_run_id = Column(Integer)
    collected_at = Column(DateTime, index=True)
    source = Column(String(20), default="playwright")

    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime)
    last_seen_at = Column(DateTime)
    last_seen_run_id = Column(Integer)

    is_active = Column(Boolean, default=True)
    classified_type = Column(String)
    classified_id = Column(Integer)
    classified_at = Column(DateTime)

    def __repr__(self):
        return f"<InstagramPostArchive(id={self.id}, post_id={self.post_id}, account={self.account})>"
