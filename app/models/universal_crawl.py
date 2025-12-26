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
    crawl_requests = relationship("UniversalCrawlRequest", back_populates="crawled_page")

    def __repr__(self):
        return f"<CrawledPage(id={self.id}, url_type={self.url_type}, title={self.title[:30] if self.title else None})>"


class UniversalCrawlRequest(Base):
    """범용 크롤링 요청 큐 모델."""

    __tablename__ = "universal_crawl_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 요청 정보
    url = Column(Text, nullable=False)
    url_type = Column(String(50), nullable=False, default="other", index=True)

    # 서비스 계정 (Playwright 기반 크롤링용)
    service_account_id = Column(Integer, ForeignKey("service_accounts.id", ondelete="SET NULL"))

    # 요청 상태
    status = Column(String(20), nullable=False, default="pending", index=True)
    requested_by = Column(String(20), default="manual")  # manual, pwa_share, api
    requested_at = Column(DateTime, default=datetime.now, index=True)

    # 처리 정보
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)

    # 결과 연결
    crawled_page_id = Column(Integer, ForeignKey("crawled_pages.id", ondelete="SET NULL"))

    # 옵션
    auto_analyze = Column(Boolean, default=True)
    priority = Column(Integer, default=0, index=True)

    # 메타데이터
    extra_metadata = Column("metadata", Text)  # JSON, 컬럼명은 metadata 유지

    # Relationships
    service_account = relationship("ServiceAccount", foreign_keys=[service_account_id])
    crawled_page = relationship("CrawledPage", back_populates="crawl_requests")

    def __repr__(self):
        return f"<UniversalCrawlRequest(id={self.id}, url_type={self.url_type}, status={self.status})>"
