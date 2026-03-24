"""
카카오톡 모니터링 관련 SQLAlchemy 모델.

Tables:
    kakao_watch_configs  - 감시 대상 채팅방 설정
    kakao_keywords       - 키워드 목록
    kakao_collected_posts - 수집된 게시물 이력
    kakao_alert_logs     - 알림 발송 이력
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class KakaoWatchConfig(Base):
    """카카오톡 감시 설정 — 채팅방 단위."""

    __tablename__ = "kakao_watch_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_name = Column(String(200), nullable=False, index=True)
    polling_interval_sec = Column(Integer, default=3, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    keywords = relationship(
        "KakaoKeyword",
        back_populates="config",
        cascade="all, delete-orphan",
    )
    collected_posts = relationship(
        "KakaoCollectedPost",
        back_populates="config",
        cascade="all, delete-orphan",
    )

    # action_type 유효값
    ACTION_TYPE_COLLECT = "collect"
    ACTION_TYPE_ALERT_ONLY = "alert_only"

    def __repr__(self) -> str:
        return f"<KakaoWatchConfig(id={self.id}, chat_name={self.chat_name!r}, active={self.is_active})>"


class KakaoKeyword(Base):
    """감시 키워드."""

    __tablename__ = "kakao_keywords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_id = Column(
        Integer,
        ForeignKey("kakao_watch_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    keyword = Column(String(200), nullable=False)
    action_type = Column(String(20), default="collect", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    # 관계
    config = relationship("KakaoWatchConfig", back_populates="keywords")
    collected_posts = relationship("KakaoCollectedPost", back_populates="keyword")

    def __repr__(self) -> str:
        return f"<KakaoKeyword(id={self.id}, keyword={self.keyword!r}, action={self.action_type})>"


class KakaoCollectedPost(Base):
    """수집된 게시물 이력."""

    __tablename__ = "kakao_collected_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_id = Column(
        Integer,
        ForeignKey("kakao_watch_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    keyword_id = Column(
        Integer,
        ForeignKey("kakao_keywords.id", ondelete="SET NULL"),
        nullable=True,
    )
    matched_keyword = Column(String(200))
    trigger_message = Column(Text)
    collected_content = Column(Text)
    collected_at = Column(DateTime, default=datetime.now, index=True)
    screenshot_path = Column(String(500), nullable=True)
    status = Column(String(20), default="success", index=True)

    # status 유효값
    STATUS_SUCCESS = "success"
    STATUS_PARTIAL = "partial"
    STATUS_FAILED = "failed"

    # 관계
    config = relationship("KakaoWatchConfig", back_populates="collected_posts")
    keyword = relationship("KakaoKeyword", back_populates="collected_posts")
    alert_logs = relationship(
        "KakaoAlertLog",
        back_populates="post",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<KakaoCollectedPost(id={self.id}, keyword={self.matched_keyword!r}, status={self.status})>"


class KakaoAlertLog(Base):
    """알림 발송 이력."""

    __tablename__ = "kakao_alert_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(
        Integer,
        ForeignKey("kakao_collected_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alert_type = Column(String(50), nullable=False)
    sent_at = Column(DateTime, default=datetime.now)
    result = Column(String(200))

    # 관계
    post = relationship("KakaoCollectedPost", back_populates="alert_logs")

    def __repr__(self) -> str:
        return f"<KakaoAlertLog(id={self.id}, post_id={self.post_id}, type={self.alert_type})>"
