"""Facebook Post SQLAlchemy Model."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class FacebookPost(Base):
    """Facebook 게시물 모델."""
    __tablename__ = "facebook_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 기본 정보
    post_id = Column(String, unique=True, nullable=False, index=True)  # Facebook 게시물 ID
    account = Column(String, nullable=False, index=True)               # 작성자
    url = Column(String)                                                # 게시물 URL

    # 콘텐츠
    caption = Column(Text)
    images = Column(JSON, default=list)  # [{"src": "...", "alt": "..."}]

    # 메타데이터
    posted_at = Column(DateTime, index=True)
    display_time = Column(String)  # 상대 시간 표시 ("3시간 전" 등)

    # Facebook 특화: Reactions 시스템
    reactions = Column(JSON, default=dict)  # {"like": 10, "love": 5, "haha": 3, ...}
    total_reactions = Column(Integer, default=0)   # 전체 반응 수
    shares = Column(Integer, default=0)            # 공유 수
    comments = Column(Integer, default=0)          # 댓글 수

    # 게시물 유형
    # NORMAL, SPONSORED, SUGGESTED, SHARED, EVENT, LINK, LIVE, GROUP_POST
    post_type = Column(String, default="NORMAL", index=True)
    original_post_url = Column(String)    # 공유 게시물인 경우 원본 URL
    link_preview = Column(JSON)           # {"title", "description", "image", "domain"}

    # 소스 유형
    source_type = Column(String, index=True)  # 'feed' | 'group' | 'page' | 'profile'
    group_id = Column(String)
    group_name = Column(String)
    page_id = Column(String)
    page_name = Column(String)

    # 수집 정보
    service_account_id = Column(Integer, ForeignKey("service_accounts.id", ondelete="SET NULL"))
    crawl_run_id = Column(Integer)
    collected_at = Column(DateTime, default=datetime.now, index=True)
    source = Column(String(20), default="playwright", index=True)

    # 추적 정보
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, index=True)
    last_seen_at = Column(DateTime, default=datetime.now, index=True)
    last_seen_run_id = Column(Integer, index=True)

    # 활성화 상태
    is_active = Column(Boolean, default=True, index=True)

    # 분류 결과 참조
    classified_type = Column(String, index=True)  # 'event' | 'popup' | 'uncategorized' | NULL
    classified_id = Column(Integer)
    classified_at = Column(DateTime, index=True)

    def __repr__(self):
        return f"<FacebookPost(id={self.id}, post_id={self.post_id}, account={self.account})>"
