"""UncategorizedPost SQLAlchemy Model - 미분류 게시물 보관."""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Date
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class UncategorizedPost(Base):
    """미분류 게시물 모델 - 홍보대사, 기타 등 분류되지 않은 LLM 분석 결과 보관."""
    __tablename__ = "uncategorized_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 분류 정보
    original_tag = Column(String, index=True)  # LLM이 분류한 원본 태그 (홍보대사, 기타 등)

    # 기본 정보 (간소화)
    title = Column(Text)  # 제목/요약
    thumbnail_url = Column(Text)  # Instagram 첫 번째 이미지
    summary = Column(Text)  # 상세 요약
    organizer = Column(String)  # 브랜드/주최

    # 기간 (있는 경우)
    start_date = Column(Date)
    end_date = Column(Date)

    # URL
    urls = Column(JSON, default=list)  # 관련 URL들

    # 출처
    source_instagram_post_id = Column(Integer, ForeignKey("instagram_posts.id", ondelete="SET NULL"), nullable=False, index=True)
    source_instagram_url = Column(Text)
    source_instagram_account = Column(String)

    # 수동 재분류
    reclassified_as = Column(String)  # 'event' | 'popup' | NULL
    reclassified_id = Column(Integer)  # 재분류된 테이블의 ID
    reclassified_at = Column(DateTime)  # 재분류 시간

    # 메타데이터
    created_at = Column(DateTime, default=datetime.now)

    # 관계
    source_instagram_post = relationship("InstagramPost", foreign_keys=[source_instagram_post_id])

    def __repr__(self):
        return f"<UncategorizedPost(id={self.id}, tag={self.original_tag}, title={self.title[:20] if self.title else 'N/A'})>"
