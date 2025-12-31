"""Crawl Schedule SQLAlchemy Models - 스케줄 설정 및 실행 이력."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
import json

from .base import Base


class CrawlSchedule(Base):
    """크롤링 스케줄 설정 모델."""

    __tablename__ = "crawl_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 스케줄 식별
    name = Column(String(100), unique=True, nullable=False)  # 'instagram_feed_account_1'
    display_name = Column(String(200), nullable=True)

    # 대상 설정
    target_type = Column(String(50), nullable=False, index=True)  # 'instagram_feed', 'naver_blog'
    target_config = Column(Text, nullable=True)  # JSON: {"account_id": 1, ...}

    # 주기 설정
    schedule_type = Column(String(20), nullable=False)  # 'cron', 'interval', 'time_window'
    schedule_value = Column(Text, nullable=True)  # cron 표현식 또는 interval 값

    # 활성화
    enabled = Column(Boolean, default=True, index=True)

    # 실행 상태
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True, index=True)

    # 메타
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    runs = relationship("CrawlScheduleRun", back_populates="schedule", cascade="all, delete-orphan")

    # 타입 상수
    TARGET_TYPE_INSTAGRAM_FEED = "instagram_feed"
    TARGET_TYPE_NAVER_BLOG = "naver_blog"
    TARGET_TYPE_NAVER_CAFE = "naver_cafe"
    TARGET_TYPE_GOOGLE_SEARCH = "google_search"

    SCHEDULE_TYPE_CRON = "cron"
    SCHEDULE_TYPE_INTERVAL = "interval"
    SCHEDULE_TYPE_TIME_WINDOW = "time_window"
    SCHEDULE_TYPE_MANUAL = "manual"

    def __repr__(self):
        return f"<CrawlSchedule(id={self.id}, name={self.name}, target_type={self.target_type})>"

    def get_target_config(self) -> dict:
        """target_config JSON을 dict로 반환."""
        if not self.target_config:
            return {}
        try:
            return json.loads(self.target_config)
        except json.JSONDecodeError:
            return {}

    def set_target_config(self, config: dict):
        """target_config를 JSON 문자열로 저장."""
        self.target_config = json.dumps(config, ensure_ascii=False)

    def update_last_run(self, next_run_at: datetime = None):
        """마지막 실행 시간 업데이트."""
        self.last_run_at = datetime.now()
        if next_run_at:
            self.next_run_at = next_run_at


class CrawlScheduleRun(Base):
    """크롤링 스케줄 실행 이력 모델."""

    __tablename__ = "crawl_schedule_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 스케줄 연결
    schedule_id = Column(Integer, ForeignKey("crawl_schedules.id", ondelete="CASCADE"), nullable=False, index=True)

    # 실행 정보
    started_at = Column(DateTime, nullable=False, default=datetime.now, index=True)
    finished_at = Column(DateTime, nullable=True)

    # 상태
    status = Column(String(20), nullable=False, default="running", index=True)
    # running, completed, failed

    # 결과 통계
    collected_count = Column(Integer, default=0)
    saved_count = Column(Integer, default=0)

    # 상세 정보
    stop_reason = Column(String(50), nullable=True)  # 'max_posts_reached', 'duplicate_stop'
    error_message = Column(Text, nullable=True)
    config_snapshot = Column(Text, nullable=True)  # JSON: 실행 시점 설정

    # 워커 정보
    worker_id = Column(String(100), nullable=True)

    # 재시도 정보
    retry_count = Column(Integer, default=0)
    retry_of_run_id = Column(Integer, ForeignKey("crawl_schedule_runs.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    schedule = relationship("CrawlSchedule", back_populates="runs")
    retry_of = relationship("CrawlScheduleRun", remote_side=[id], foreign_keys=[retry_of_run_id])

    # 상태 상수
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    # 정지 사유 상수
    STOP_REASON_MAX_POSTS = "max_posts_reached"
    STOP_REASON_DUPLICATE = "duplicate_stop"
    STOP_REASON_MAX_REFRESH = "max_refresh_after_duplicates"
    STOP_REASON_TIMEOUT = "timeout"
    STOP_REASON_ERROR = "error"
    STOP_REASON_SHUTDOWN = "shutdown"
    STOP_REASON_SEARCH_COMPLETED = "search_completed"
    STOP_REASON_CAPTCHA = "captcha_detected"

    def __repr__(self):
        return f"<CrawlScheduleRun(id={self.id}, schedule_id={self.schedule_id}, status={self.status})>"

    def get_config_snapshot(self) -> dict:
        """config_snapshot JSON을 dict로 반환."""
        if not self.config_snapshot:
            return {}
        try:
            return json.loads(self.config_snapshot)
        except json.JSONDecodeError:
            return {}

    def set_config_snapshot(self, config: dict):
        """config_snapshot을 JSON 문자열로 저장."""
        self.config_snapshot = json.dumps(config, ensure_ascii=False)

    def mark_completed(self, collected_count: int, saved_count: int, stop_reason: str = None):
        """완료로 표시."""
        self.status = self.STATUS_COMPLETED
        self.finished_at = datetime.now()
        self.collected_count = collected_count
        self.saved_count = saved_count
        self.stop_reason = stop_reason

    def mark_failed(self, error_message: str):
        """실패로 표시."""
        self.status = self.STATUS_FAILED
        self.finished_at = datetime.now()
        self.error_message = error_message

    @property
    def duration_seconds(self) -> int | None:
        """실행 시간(초) 반환."""
        if self.finished_at and self.started_at:
            return int((self.finished_at - self.started_at).total_seconds())
        return None
