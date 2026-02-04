"""
모바일 크롤링 모델

모바일 전용 페이지의 크롤링 대상 및 수집 아이템을 관리합니다.
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, TIMESTAMP, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base


class MobileCrawlTarget(Base):
    """모바일 크롤링 대상"""

    __tablename__ = "mobile_crawl_targets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False, unique=True)
    crawl_type = Column(String, nullable=False, default="list")
    parse_config = Column(Text, nullable=False)  # JSON
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    items = relationship(
        "MobileCrawlItem",
        back_populates="target",
        cascade="all, delete-orphan"
    )


class MobileCrawlItem(Base):
    """모바일 크롤링 수집 아이템"""

    __tablename__ = "mobile_crawl_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_id = Column(Integer, ForeignKey("mobile_crawl_targets.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(Integer, ForeignKey("task_schedule_runs.id", ondelete="SET NULL"), nullable=True)

    # 아이템 정보
    title = Column(String, nullable=False)
    item_url = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    attributes = Column(Text, nullable=True)  # JSON
    raw_html = Column(Text, nullable=True)

    # 변경 감지
    first_seen_at = Column(TIMESTAMP, default=datetime.utcnow)
    last_seen_at = Column(TIMESTAMP, default=datetime.utcnow)
    is_changed = Column(Boolean, default=False)

    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    target = relationship("MobileCrawlTarget", back_populates="items")
