"""Instagram Post SQLAlchemy Model."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Date, Float
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
    post_type = Column(String, default="NORMAL", index=True)  # NORMAL, SPONSORED, SUGGESTED
    likes = Column(Integer)  # 좋아요 수
    comments = Column(Integer)  # 댓글 수

    # 릴스 메타데이터
    is_reel = Column(Boolean, default=False, index=True)  # 릴스 여부
    duration = Column(Float)  # 재생 시간 (초)
    music_title = Column(Text)  # 사용된 음악 제목
    music_artist = Column(Text)  # 음악 아티스트

    # 수집 정보
    service_account_id = Column(Integer, ForeignKey("service_accounts.id", ondelete="SET NULL"))
    crawl_run_id = Column(Integer, ForeignKey("instagram_crawl_runs.id", ondelete="SET NULL"))
    collected_at = Column(DateTime, default=datetime.now, index=True)

    # 활성화 상태
    is_active = Column(Boolean, default=True, index=True)

    # 분류 결과 참조 (Event/Popup/Uncategorized)
    classified_type = Column(String, index=True)  # 'event' | 'popup' | 'uncategorized' | NULL
    classified_id = Column(Integer)  # 각 테이블의 ID
    classified_at = Column(DateTime, index=True)  # AI 분류 완료 시각

    # 관계
    crawl_run = relationship("InstagramCrawlRun", back_populates="posts")
    tag_relations = relationship(
        "InstagramPostTagRelation",
        back_populates="post",
        cascade="all, delete-orphan",
    )
    # LLM 분류 요청 (최신순)
    llm_requests = relationship(
        "InstagramLLMClassificationRequest",
        back_populates="post",
        order_by="desc(InstagramLLMClassificationRequest.requested_at)",
    )

    @property
    def tags(self) -> list[str]:
        """태그 이름 목록 반환."""
        return [rel.tag.name for rel in self.tag_relations if rel.tag]

    def __repr__(self):
        return f"<InstagramPost(id={self.id}, post_id={self.post_id}, account={self.account})>"
