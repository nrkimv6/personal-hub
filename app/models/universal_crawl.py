"""Universal Crawl Queue SQLAlchemy Models."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class CrawledPage(Base):
    """크롤링된 페이지 결과 모델."""

    __tablename__ = "crawled_pages"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 원본 정보
    url = Column(Text, nullable=False)
    url_type = Column(String(50), nullable=False, index=True)

    # 추출 결과
    title = Column(Text)
    description = Column(Text)
    content = Column(Text)
    extracted_data = Column(Text)  # JSON

    # 메타데이터
    og_title = Column(Text)
    og_description = Column(Text)
    og_image = Column(Text)

    # 상태
    crawled_at = Column(DateTime, default=datetime.now, index=True)
    extractor_used = Column(String(100))

    # AI 분석 결과
    is_event = Column(Boolean)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="SET NULL"))
    popup_id = Column(Integer, ForeignKey("popups.id", ondelete="SET NULL"))
    analysis_result = Column(Text)  # JSON

    # 중복 방지
    url_hash = Column(String(32), unique=True, index=True)

    # Relationships
    event = relationship("Event", foreign_keys=[event_id])
    popup = relationship("Popup", foreign_keys=[popup_id])

    def __repr__(self):
        return f"<CrawledPage(id={self.id}, url_type={self.url_type}, title={self.title[:30] if self.title else None})>"
