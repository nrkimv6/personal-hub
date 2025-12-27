"""
Google 검색 관련 모델
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class GoogleSavedSearch(Base):
    """저장된 검색 조건 모델."""

    __tablename__ = "google_saved_searches"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 검색 조건
    name = Column(String(255), nullable=False)
    query = Column(String(500), nullable=False)
    date_filter = Column(String(10), nullable=True)  # 1h, 24h, 1w, 1m, 1y
    max_pages = Column(Integer, default=1)

    # 옵션
    service_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    is_favorite = Column(Boolean, default=False)

    # 마지막 실행 정보
    last_search_id = Column(String(36), nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    last_result_count = Column(Integer, nullable=True)

    # 메타
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    account = relationship("Account", backref="google_saved_searches")

    def __repr__(self) -> str:
        return f"<GoogleSavedSearch(id={self.id}, name='{self.name}', query='{self.query}')>"


class GoogleSearchHistory(Base):
    """검색 히스토리 모델."""

    __tablename__ = "google_search_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    search_id = Column(String(36), unique=True, nullable=False)
    query = Column(String(500), nullable=False)
    date_filter = Column(String(10), nullable=True)
    max_pages = Column(Integer, default=1)

    # 상태
    status = Column(String(20), default="pending")  # pending, running, completed, failed
    total_results = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    # 시간
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    # 관계
    results = relationship(
        "GoogleSearchResult",
        back_populates="history",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<GoogleSearchHistory(search_id='{self.search_id}', query='{self.query}', status='{self.status}')>"


class GoogleSearchResult(Base):
    """검색 결과 모델."""

    __tablename__ = "google_search_results"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 검색 정보
    search_id = Column(
        String(36),
        ForeignKey("google_search_history.search_id", ondelete="CASCADE"),
        nullable=False,
    )
    query = Column(String(500), nullable=False)

    # 결과 데이터
    rank = Column(Integer, nullable=False)
    title = Column(String(500), nullable=False)
    url = Column(Text, nullable=False)
    display_url = Column(String(500), nullable=True)
    snippet = Column(Text, nullable=True)
    publish_date = Column(String(100), nullable=True)

    # 필터 정보
    date_filter = Column(String(10), nullable=True)
    page_number = Column(Integer, default=1)

    # 메타
    created_at = Column(DateTime, default=datetime.now)

    # 관계
    history = relationship("GoogleSearchHistory", back_populates="results")

    def __repr__(self) -> str:
        return f"<GoogleSearchResult(rank={self.rank}, title='{self.title[:30]}...')>"
