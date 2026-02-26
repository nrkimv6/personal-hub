"""
TestRun / TestResult SQLAlchemy Models — pytest 자동 실행 이력 저장.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.models.base import Base


class TestRun(Base):
    """pytest 실행 이력."""

    __tablename__ = "test_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 실행 시각
    started_at = Column(DateTime, nullable=False, default=datetime.now, index=True)
    finished_at = Column(DateTime, nullable=True)

    # 상태
    status = Column(String(20), nullable=False, default="running", index=True)
    # running / completed / failed

    # 결과 통계
    total_tests = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    skipped = Column(Integer, default=0)

    # 소요 시간 (초)
    duration_seconds = Column(Float, nullable=True)

    # 스케줄 연결 (nullable)
    schedule_run_id = Column(Integer, ForeignKey("task_schedule_runs.id", ondelete="SET NULL"), nullable=True)

    # 파일 경로
    log_file_path = Column(String(500), nullable=True)
    xml_file_path = Column(String(500), nullable=True)

    # 트리거 정보
    triggered_by = Column(String(20), nullable=False, default="manual")
    # scheduler / manual / api

    # 실행 설정
    test_path = Column(String(500), nullable=True, default="tests/")
    extra_args = Column(Text, nullable=True)  # JSON 배열

    # Relationships
    results = relationship("TestResult", back_populates="test_run", cascade="all, delete-orphan")
    schedule_run = relationship("TaskScheduleRun", foreign_keys=[schedule_run_id])

    # 상태 상수
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    TRIGGERED_BY_SCHEDULER = "scheduler"
    TRIGGERED_BY_MANUAL = "manual"
    TRIGGERED_BY_API = "api"

    def __repr__(self):
        return f"<TestRun(id={self.id}, status={self.status}, total={self.total_tests})>"

    def mark_completed(self, total: int, passed: int, failed: int, errors: int, skipped: int):
        self.status = self.STATUS_COMPLETED
        self.finished_at = datetime.now()
        self.total_tests = total
        self.passed = passed
        self.failed = failed
        self.errors = errors
        self.skipped = skipped
        if self.started_at:
            self.duration_seconds = (self.finished_at - self.started_at).total_seconds()

    def mark_failed(self, error_message: str = None):
        self.status = self.STATUS_FAILED
        self.finished_at = datetime.now()
        if self.started_at:
            self.duration_seconds = (self.finished_at - self.started_at).total_seconds()

    __table_args__ = (
        Index("ix_test_runs_status_started", "status", "started_at"),
    )


class TestResult(Base):
    """개별 테스트 케이스 결과."""

    __tablename__ = "test_results"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 실행 연결
    test_run_id = Column(Integer, ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True)

    # 테스트 식별 (full qualified name)
    test_name = Column(String(1000), nullable=False)
    # 예: tests/test_foo.py::TestClass::test_method

    # 상태
    status = Column(String(20), nullable=False, index=True)
    # passed / failed / error / skipped

    # 소요 시간
    duration_seconds = Column(Float, nullable=True, default=0.0, index=True)

    # 실패 정보
    error_message = Column(Text, nullable=True)
    traceback = Column(Text, nullable=True)

    # LLM 수정 계획
    fix_plan = Column(Text, nullable=True)
    # llm_requests는 claude_worker 모듈 전용 → ORM FK 없이 Integer만 보관
    llm_request_id = Column(Integer, nullable=True)

    # Relationships
    test_run = relationship("TestRun", back_populates="results")

    # 상태 상수
    STATUS_PASSED = "passed"
    STATUS_FAILED = "failed"
    STATUS_ERROR = "error"
    STATUS_SKIPPED = "skipped"

    def __repr__(self):
        return f"<TestResult(id={self.id}, name={self.test_name[:40]}, status={self.status})>"

    __table_args__ = (
        Index("ix_test_results_run_status", "test_run_id", "status"),
        Index("ix_test_results_duration", "test_run_id", "duration_seconds"),
    )
