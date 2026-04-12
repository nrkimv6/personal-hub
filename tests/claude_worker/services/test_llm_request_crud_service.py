"""LLMRequestCrudService TC (Task 27)."""
import pytest
from datetime import datetime
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
    from app.modules.claude_worker.services.llm_request_crud_service import LLMRequestCrudService
    return LLMRequestCrudService(LLMRequestRepository(db), db)


def _req(db, caller_id="ci", status="pending", **kw):
    r = LLMRequest(caller_type="ct", caller_id=caller_id, prompt="p", status=status, **kw)
    db.add(r)
    db.flush()
    return r


class TestBatchRetry:
    def test_batch_retry_R_resets_status(self, db, svc):
        """R: failed → pending 일괄 전환."""
        r1 = _req(db, "r1", status="failed", error_message="err")
        r2 = _req(db, "r2", status="failed", error_message="err")
        result = svc.batch_retry([r1.id, r2.id])
        assert result["success"] == 2
        db.refresh(r1)
        db.refresh(r2)
        assert r1.status == "pending"
        assert r2.status == "pending"
        assert r1.error_message is None

    def test_batch_retry_B_skips_non_failed(self, db, svc):
        """B: failed 아닌 요청 → skipped."""
        r = _req(db, "r3", status="pending")
        result = svc.batch_retry([r.id])
        assert result["skipped"] == 1
        assert result["success"] == 0

    def test_batch_retry_B_empty_list(self, db, svc):
        """B: 빈 목록 → 모두 0."""
        result = svc.batch_retry([])
        assert result == {"success": 0, "failed": 0, "skipped": 0}


class TestBatchDelete:
    def test_batch_delete_R_soft_delete(self, db, svc):
        """R: soft delete → deleted_at 설정."""
        r1 = _req(db, "d1")
        r2 = _req(db, "d2")
        result = svc.batch_delete([r1.id, r2.id], hard_delete=False)
        assert result["deleted"] == 2
        db.refresh(r1)
        assert r1.deleted_at is not None

    def test_batch_delete_B_empty_list(self, db, svc):
        """B: 빈 목록."""
        result = svc.batch_delete([])
        assert result == {"deleted": 0, "skipped": 0}

    def test_batch_delete_B_nonexistent_id(self, db, svc):
        """B: 없는 ID → skipped."""
        result = svc.batch_delete([99999])
        assert result["skipped"] == 1


class TestCancelRequest:
    def test_cancel_request_R_pending_to_cancelled(self, db, svc):
        """R: pending → cancelled."""
        r = _req(db, "c1", status="pending")
        ok = svc.cancel_request(r.id)
        assert ok is True
        db.refresh(r)
        assert r.status == "cancelled"

    def test_cancel_request_B_not_pending(self, db, svc):
        """B: completed 상태는 취소 불가."""
        r = _req(db, "c2", status="completed")
        ok = svc.cancel_request(r.id)
        assert ok is False


class TestUpdateRequest:
    def test_update_request_R_updates_prompt(self, db, svc):
        """R: prompt 갱신."""
        r = _req(db, "u1", status="pending")
        updated = svc.update_request(r.id, prompt="new prompt")
        assert updated is not None
        db.refresh(r)
        assert r.prompt == "new prompt"

    def test_update_request_B_completed_returns_none(self, db, svc):
        """B: completed 상태 → None 반환."""
        r = _req(db, "u2", status="completed")
        result = svc.update_request(r.id, prompt="changed")
        assert result is None
