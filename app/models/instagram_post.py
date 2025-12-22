"""Instagram Post SQLAlchemy Model."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Date
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
    likes = Column(Integer)  # 좋아요 수
    comments = Column(Integer)  # 댓글 수

    # 수집 정보
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"))
    crawl_run_id = Column(Integer, ForeignKey("instagram_crawl_runs.id", ondelete="SET NULL"))
    collected_at = Column(DateTime, default=datetime.now, index=True)

    # LLM 분류 결과
    llm_status = Column(String, index=True)  # pending/processing/completed/failed
    llm_tag = Column(String, index=True)  # 이벤트/팝업/홍보대사/기타
    llm_purchase_required = Column(String)  # 예_전부/예_부분/아니오
    llm_prizes = Column(JSON)  # ["경품1", "경품2"]
    llm_winner_count = Column(Integer)
    llm_event_start = Column(Date)
    llm_event_end = Column(Date)
    llm_announcement_date = Column(Date)
    llm_urls = Column(JSON)  # ["https://..."]
    llm_organizer = Column(String)
    llm_summary = Column(Text)
    llm_analyzed_at = Column(DateTime)

    # 관계
    crawl_run = relationship("InstagramCrawlRun", back_populates="posts")
    tag_relations = relationship(
        "InstagramPostTagRelation",
        back_populates="post",
        cascade="all, delete-orphan",
    )

    @property
    def tags(self) -> list[str]:
        """태그 이름 목록 반환."""
        return [rel.tag.name for rel in self.tag_relations if rel.tag]

    def __repr__(self):
        return f"<InstagramPost(id={self.id}, post_id={self.post_id}, account={self.account})>"
