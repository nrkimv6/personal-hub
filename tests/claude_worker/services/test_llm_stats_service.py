"""LLMStatsService TC (Task 27)."""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def svc(db):
    from app.modules.claude_worker.services.repositories import LLMRequestRepository
    from app.modules.claude_worker.services.llm_stats_service import LLMStatsService
    return LLMStatsService(LLMRequestRepository(db), db)


def _req(db, caller_id="ci", status="processing", requested_at=None, processed_at=None, **kw):
    r = LLMRequest(
        caller_type="ct",
        caller_id=caller_id,
        prompt="p",
        status=status,
        requested_at=requested_at or datetime.now(),
        processed_at=processed_at,
        **kw,
    )
    db.add(r)
    db.flush()
    return r


class TestCleanupStaleProcessing:
    def test_cleanup_stale_processing_B_boundary_minutes(self, db, svc):
        """B: timeout_minutes 경계값 — 시간 초과 → failed, 미초과 → 유지."""
        old = _req(db, "old", status="processing",
                   requested_at=datetime.now() - timedelta(minutes=70))
        fresh = _req(db, "fresh", status="processing",
                     requested_at=datetime.now() - timedelta(minutes=10))

        count = svc.cleanup_stale_processing(timeout_minutes=65)
        assert count == 1
        db.refresh(old)
        db.refresh(fresh)
        assert old.status == "failed"
        assert fresh.status == "processing"

    def test_cleanup_stale_processing_B_no_stale(self, db, svc):
        """B: stale 없으면 0 반환."""
        _req(db, "fresh2", status="processing",
             requested_at=datetime.now() - timedelta(minutes=5))
        count = svc.cleanup_stale_processing(timeout_minutes=65)
        assert count == 0

    def test_cleanup_stale_processing_B_default_timeout(self, db, svc):
        """B: 기본 timeout_minutes=65 사용 확인."""
        old = _req(db, "old2", status="processing",
                   requested_at=datetime.now() - timedelta(minutes=70))
        count = svc.cleanup_stale_processing()  # default
        assert count == 1

    def test_cleanup_stale_processing_R_uses_processed_at_when_available(self, db, svc):
        """R: processing 시작 시각(processed_at)이 있으면 requested_at보다 우선한다."""
        old_requested_but_recently_started = _req(
            db,
            "recent-start",
            status="processing",
            requested_at=datetime.now() - timedelta(hours=2),
            processed_at=datetime.now() - timedelta(minutes=5),
        )
        old_started = _req(
            db,
            "old-start",
            status="processing",
            requested_at=datetime.now() - timedelta(minutes=10),
            processed_at=datetime.now() - timedelta(minutes=70),
        )

        count = svc.cleanup_stale_processing(timeout_minutes=65)

        assert count == 1
        db.refresh(old_requested_but_recently_started)
        db.refresh(old_started)
        assert old_requested_but_recently_started.status == "processing"
        assert old_started.status == "failed"


class TestCleanupOldHistory:
    def test_cleanup_old_history_R_default_soft_delete(self, db, svc):
        """R: hard_delete 생략 시 soft delete."""
        old_time = datetime.now() - timedelta(days=10)
        r = _req(db, "oh-default", status="completed", processed_at=old_time)

        count = svc.cleanup_old_history(days=7)

        assert count == 1
        db.refresh(r)
        assert r.deleted_at is not None
        assert db.get(LLMRequest, r.id) is not None

    def test_cleanup_old_history_B_boundary_days(self, db, svc):
        """B: days 경계값 — 오래된 completed → 삭제, 최근 → 유지."""
        old_time = datetime.now() - timedelta(days=10)
        old_req = _req(db, "oh1", status="completed", processed_at=old_time)
        recent_req = _req(db, "oh2", status="completed",
                          processed_at=datetime.now() - timedelta(hours=1))

        count = svc.cleanup_old_history(days=7, hard_delete=True)
        assert count == 1

    def test_cleanup_old_history_B_soft_delete(self, db, svc):
        """B: hard_delete=False → soft delete."""
        old_time = datetime.now() - timedelta(days=10)
        r = _req(db, "oh3", status="completed", processed_at=old_time)
        count = svc.cleanup_old_history(days=7, hard_delete=False)
        assert count == 1
        db.refresh(r)
        assert r.deleted_at is not None

    def test_cleanup_old_history_B_pending_excluded(self, db, svc):
        """B: pending 상태는 삭제 대상 아님."""
        old_time = datetime.now() - timedelta(days=10)
        r = _req(db, "oh4", status="pending", requested_at=old_time)
        count = svc.cleanup_old_history(days=7)
        assert count == 0

    def test_cleanup_old_history_E_already_deleted_excluded_with_default(self, db, svc):
        """E: 이미 soft delete된 오래된 요청은 기본 cleanup에서 제외."""
        old_time = datetime.now() - timedelta(days=10)
        _req(
            db,
            "oh-deleted",
            status="completed",
            processed_at=old_time,
            deleted_at=datetime.now() - timedelta(days=1),
        )

        count = svc.cleanup_old_history(days=7)

        assert count == 0


class TestGetStats:
    def test_get_stats_R_counts(self, db, svc):
        """R: 상태별 카운트."""
        _req(db, "s1", status="pending")
        _req(db, "s2", status="pending")
        _req(db, "s3", status="completed")

        result = svc.get_stats()
        assert result["pending"] == 2
        assert result["completed"] == 1
        assert result["total"] >= 3


class TestRunCleanup:
    def test_run_cleanup_R_returns_dict(self, db, svc):
        """R: run_cleanup → dict with stale_processing, old_history."""
        result = svc.run_cleanup()
        assert "stale_processing" in result
        assert "old_history" in result
