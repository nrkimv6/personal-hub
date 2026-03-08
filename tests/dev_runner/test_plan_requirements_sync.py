"""
test_plan_requirements_sync.py — _maybe_queue_requirements_sync() 단위 테스트

Bug 2: 카테고리별 요구사항 문서가 영원히 자동 생성되지 않는 버그 수정 검증
  - 수정 전: 트리거 누락 또는 조건 미달
  - 수정 후: processed 5개+ 시 LLMRequest(plan_requirements_sync) 자동 생성

RIGHT-BICEP:
- R: 정상 케이스 — 5개 이상 시 큐 등록
- B: 경계 케이스 — 4개(미등록), 딱 5개(등록)
- E: 오류 케이스 — 24시간 내 중복 방지
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.plan_analyze_handler import (
    _maybe_queue_requirements_sync,
    build_requirements_sync_prompt,
)


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    LLMRequest.__table__.create(bind=eng, checkfirst=True)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


class TestMaybeQueueRequirementsSync:
    """_maybe_queue_requirements_sync() 단위 테스트"""

    def test_maybe_queue_requirements_sync_right_queues_when_enough(self, db):
        """R: category="instagram", processed 5개 → LLMRequest 1개 생성 확인"""
        # Arrange: 5개의 처리된 레코드 생성
        for i in range(5):
            r = PlanRecord(
                filename_hash=f"hash_{i}",
                file_path=f"/path/to/plan_{i}.md",
                category="instagram",
                summary=f"요약 {i}",
                llm_processed_at=datetime.now(),
                archived_at=datetime.now(),
            )
            db.add(r)
        db.commit()

        # Act
        result = _maybe_queue_requirements_sync(db, "instagram")

        # Assert
        assert result is True
        req = db.query(LLMRequest).filter_by(
            caller_type="plan_requirements_sync",
            caller_id="instagram"
        ).first()
        assert req is not None
        assert "요약 0" in req.prompt
        assert "요약 4" in req.prompt

    def test_maybe_queue_requirements_sync_boundary_4_records(self, db):
        """B: processed 4개 → LLMRequest 생성 안 됨"""
        # Arrange: 4개만 생성
        for i in range(4):
            r = PlanRecord(
                filename_hash=f"hash_{i}",
                file_path=f"/path/to/plan_{i}.md",
                category="instagram",
                summary=f"요약 {i}",
                llm_processed_at=datetime.now(),
                archived_at=datetime.now(),
            )
            db.add(r)
        db.commit()

        # Act
        result = _maybe_queue_requirements_sync(db, "instagram")

        # Assert
        assert result is False
        req_count = db.query(LLMRequest).filter_by(
            caller_type="plan_requirements_sync",
            caller_id="instagram"
        ).count()
        assert req_count == 0

    def test_maybe_queue_requirements_sync_boundary_exactly_5(self, db):
        """B: processed 정확히 5개 → LLMRequest 1개 생성"""
        for i in range(5):
            db.add(PlanRecord(
                filename_hash=f"exactly_{i}",
                file_path=f"file_{i}.md",
                category="naver",
                summary="sum",
                llm_processed_at=datetime.now(),
                archived_at=datetime.now(),
            ))
        db.commit()

        result = _maybe_queue_requirements_sync(db, "naver")
        assert result is True
        assert db.query(LLMRequest).filter_by(caller_id="naver").count() == 1

    def test_maybe_queue_requirements_sync_error_duplicate_24h(self, db):
        """E: 24시간 내 이미 pending 요청 존재 → 중복 생성 안 됨"""
        # Arrange: 5개 레코드 + 이미 존재하는 요청
        for i in range(5):
            db.add(PlanRecord(
                filename_hash=f"dup_{i}",
                file_path=f"file_{i}.md",
                category="instagram",
                summary="sum",
                llm_processed_at=datetime.now(),
                archived_at=datetime.now(),
            ))
        
        existing_req = LLMRequest(
            caller_type="plan_requirements_sync",
            caller_id="instagram",
            prompt="existing",
            requested_at=datetime.now() - timedelta(hours=1)
        )
        db.add(existing_req)
        db.commit()

        # Act
        result = _maybe_queue_requirements_sync(db, "instagram")

        # Assert
        assert result is False
        assert db.query(LLMRequest).filter_by(caller_id="instagram").count() == 1

    def test_maybe_queue_requirements_sync_right_limits_50_summaries(self, db):
        """R: processed 80개 → prompt에 최대 50개 summary만 포함"""
        # Arrange: 80개 생성
        for i in range(80):
            db.add(PlanRecord(
                filename_hash=f"large_{i}",
                file_path=f"file_{i}.md",
                category="large-cat",
                summary=f"summary_{i:03d}",
                llm_processed_at=datetime.now() + timedelta(minutes=i),
                archived_at=datetime.now() + timedelta(minutes=i),
            ))
        db.commit()

        # Act
        _maybe_queue_requirements_sync(db, "large-cat")

        # Assert
        req = db.query(LLMRequest).filter_by(caller_id="large-cat").first()
        # 최신 50개면 summary_079 ~ summary_030 이 포함되어야 함 (order_by desc이므로)
        assert "summary_079" in req.prompt
        assert "summary_030" in req.prompt
        assert "summary_029" not in req.prompt

    def test_process_unqueued_requirements_sync_right_multiple_categories(self, db):
        """R: instagram/naver 각 5개+ → 두 카테고리 모두 LLMRequest 생성"""
        from app.worker.scheduled_worker import ScheduledCrawlWorker
        worker = ScheduledCrawlWorker.__new__(ScheduledCrawlWorker)
        worker.name = "test_worker"

        # Arrange
        for cat in ["instagram", "naver"]:
            for i in range(5):
                db.add(PlanRecord(
                    filename_hash=f"{cat}_{i}",
                    file_path=f"{cat}_{i}.md",
                    category=cat,
                    summary="sum",
                    llm_processed_at=datetime.now(),
                    archived_at=datetime.now(),
                ))
        db.commit()

        # Act
        with patch("app.worker.scheduled_worker.SessionLocal", return_value=db):
            worker._process_unqueued_requirements_sync()

        # Assert
        assert db.query(LLMRequest).filter_by(caller_id="instagram").count() == 1
        assert db.query(LLMRequest).filter_by(caller_id="naver").count() == 1

    def test_process_unqueued_requirements_sync_boundary_no_eligible(self, db):
        """B: 모든 카테고리 4개 이하 → 0개 생성"""
        from app.worker.scheduled_worker import ScheduledCrawlWorker
        worker = ScheduledCrawlWorker.__new__(ScheduledCrawlWorker)
        worker.name = "test_worker"

        for i in range(4):
            db.add(PlanRecord(
                filename_hash=f"low_{i}",
                file_path=f"low_{i}.md",
                category="low-cat",
                summary="sum",
                llm_processed_at=datetime.now(),
                archived_at=datetime.now(),
            ))
        db.commit()

        with patch("app.worker.scheduled_worker.SessionLocal", return_value=db):
            worker._process_unqueued_requirements_sync()

        assert db.query(LLMRequest).count() == 0
