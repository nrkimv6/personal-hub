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
    service_account_id = Column(Integer, ForeignKey("service_accounts.id", ondelete="SET NULL"), nullable=True)
    is_favorite = Column(Boolean, default=False)
    search_params = Column(Text, nullable=True)  # JSON: {lr, cr, as_sitesearch, num}
    notify_on_new = Column(Boolean, default=False)  # 신규 결과 발견 시 알림 (v097 추가)

    # 마지막 실행 정보
    last_search_id = Column(String(36), nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    last_result_count = Column(Integer, nullable=True)

    # 메타
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    service_account = relationship("ServiceAccount", backref="google_saved_searches")

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


class GoogleSearchQueue(Base):
    """Google 검색 큐 모델.

    API 요청을 큐에 저장하고 워커에서 처리합니다.
    Session 0 (NSSM 서비스)에서는 브라우저를 사용할 수 없으므로
    사용자 세션의 워커에서 처리합니다.

    Redis 큐 지원:
    - Redis 연결 시: Redis 큐에 추가 (status=queued)
    - Redis 미연결 시: SQLite 폴링 (status=pending)
    """

    __tablename__ = "google_search_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 검색 조건
    search_id = Column(String(36), unique=True, nullable=False)
    query = Column(String(500), nullable=False)
    date_filter = Column(String(10), nullable=True)
    max_pages = Column(Integer, default=1)
    search_params = Column(Text, nullable=True)  # JSON: {lr, cr, as_sitesearch, num}

    # 참조
    service_account_id = Column(
        Integer,
        ForeignKey("service_accounts.id", ondelete="SET NULL"),
        nullable=True
    )
    saved_search_id = Column(
        Integer,
        ForeignKey("google_saved_searches.id", ondelete="SET NULL"),
        nullable=True
    )
    schedule_id = Column(
        Integer,
        ForeignKey("task_schedules.id", ondelete="SET NULL"),
        nullable=True
    )

    # 상태
    status = Column(String(20), default="pending")  # pending, queued, processing, completed, failed
    error_message = Column(Text, nullable=True)
    result_count = Column(Integer, default=0)

    # 상태 상수
    STATUS_PENDING = "pending"    # SQLite 폴링 모드용
    STATUS_QUEUED = "queued"      # Redis 큐에 들어감
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    # 시간
    created_at = Column(DateTime, default=datetime.now)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # 관계
    service_account = relationship("ServiceAccount", foreign_keys=[service_account_id])
    saved_search = relationship("GoogleSavedSearch", foreign_keys=[saved_search_id])
    schedule = relationship("TaskSchedule", foreign_keys=[schedule_id])

    def __repr__(self) -> str:
        return f"<GoogleSearchQueue(search_id='{self.search_id}', query='{self.query}', status='{self.status}')>"


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

    # 신규 결과 감지 (v097 추가)
    is_new = Column(Boolean, default=False)        # 이 런에서 최초 등장
    rank_change = Column(Integer, nullable=True)   # 순위 변화 (양수=상승, 음수=하락)
    prev_rank = Column(Integer, nullable=True)     # 이전 런에서의 순위

    # 관리 기능 (v097 추가)
    is_read = Column(Boolean, default=False)       # 읽음 여부
    is_bookmarked = Column(Boolean, default=False) # 북마크 여부
    memo = Column(Text, nullable=True)             # 메모

    # 메타
    created_at = Column(DateTime, default=datetime.now)

    # 관계
    history = relationship("GoogleSearchHistory", back_populates="results")

    def __repr__(self) -> str:
        return f"<GoogleSearchResult(rank={self.rank}, title='{self.title[:30]}...')>"
