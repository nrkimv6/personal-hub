"""Instagram Post Tag SQLAlchemy Models.

게시물 분류를 위한 태그, 키워드, 관계 모델.
"""

from sqlalchemy import Column, Integer, String, Boolean, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class InstagramPostTag(Base):
    """게시물 태그 정의."""

    __tablename__ = "instagram_post_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    description = Column(Text)
    color = Column(String, default="#6b7280")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    keywords = relationship(
        "InstagramTagKeyword",
        back_populates="tag",
        cascade="all, delete-orphan",
    )
    post_relations = relationship(
        "InstagramPostTagRelation",
        back_populates="tag",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<InstagramPostTag(id={self.id}, name={self.name})>"


class InstagramTagKeyword(Base):
    """태그별 키워드."""

    __tablename__ = "instagram_tag_keywords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(
        Integer,
        ForeignKey("instagram_post_tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    keyword = Column(String, nullable=False)
    is_regex = Column(Boolean, default=False)
    is_case_sensitive = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tag = relationship("InstagramPostTag", back_populates="keywords")

    def __repr__(self):
        return f"<InstagramTagKeyword(id={self.id}, keyword={self.keyword})>"


class InstagramPostTagRelation(Base):
    """게시물-태그 관계 (N:M)."""

    __tablename__ = "instagram_post_tag_relations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(
        Integer,
        ForeignKey("instagram_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id = Column(
        Integer,
        ForeignKey("instagram_post_tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matched_keywords = Column(Text)  # JSON array
    confidence = Column(Float, default=1.0)
    classified_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    post = relationship("InstagramPost", back_populates="tag_relations")
    tag = relationship("InstagramPostTag", back_populates="post_relations")

    def __repr__(self):
        return f"<InstagramPostTagRelation(post_id={self.post_id}, tag_id={self.tag_id})>"
