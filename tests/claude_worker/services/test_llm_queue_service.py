"""LLMQueueService TC (Task 27)."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock
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
    from app.modules.claude_worker.services.llm_queue_service import LLMQueueService

    repo = LLMRequestRepository(db)
    config_svc = MagicMock()
    config_svc.resolve_provider_model.return_value = ("claude", "claude-opus-4-6")
    return LLMQueueService(repo, config_svc, db)


class TestEnqueue:
    def test_enqueue_R_creates_request(self, db, svc):
        """R: 정상 enqueue → DB 저장."""
        req = svc.enqueue("instagram", "post_1", "test prompt", requested_by="api")
        assert req.id is not None
        assert req.status == "pending"
        assert req.caller_type == "instagram"
        assert req.caller_id == "post_1"

    def test_enqueue_B_dedup_existing(self, db, svc):
        """B: 동일 caller+queue 중복 → 기존 반환."""
        req1 = svc.enqueue("instagram", "post_2", "first prompt")
        req2 = svc.enqueue("instagram", "post_2", "second prompt")
        assert req1.id == req2.id

    def test_enqueue_R_uses_resolved_provider_model(self, db, svc):
        """R: resolve_provider_model 결과가 request에 저장됨."""
        req = svc.enqueue("instagram", "post_3", "prompt")
        assert req.provider == "claude"
        assert req.model == "claude-opus-4-6"


class TestMarkStateTransitions:
    def test_mark_processing_R_state_transition(self, db, svc):
        """R: pending → processing 전이."""
        req = svc.enqueue("ct", "ci1", "prompt")
        svc.mark_processing(req.id)
        db.refresh(req)
        assert req.status == "processing"

    def test_mark_completed_R_stores_result(self, db, svc):
        """R: mark_completed → result 저장."""
        req = svc.enqueue("ct", "ci2", "prompt")
        svc.mark_completed(req.id, {"key": "val"}, raw_response="raw")
        db.refresh(req)
        assert req.status == "completed"
        assert req.processed_at is not None

    def test_mark_failed_R_increments_retry(self, db, svc):
        """R: mark_failed → retry_count 증가."""
        req = svc.enqueue("ct", "ci3", "prompt")
        initial = req.retry_count
        svc.mark_failed(req.id, "some error")
        db.refresh(req)
        assert req.status == "failed"
        assert req.retry_count == initial + 1

    def test_mark_failed_E_nonexistent(self, db, svc):
        """E: 없는 request ID → 무시 (예외 없음)."""
        svc.mark_failed(99999, "error")  # should not raise

    def test_reset_to_pending_R_from_failed(self, db, svc):
        """R: failed → pending 리셋."""
        req = svc.enqueue("ct", "ci4", "prompt")
        svc.mark_failed(req.id, "err")
        result = svc.reset_to_pending(req.id)
        db.refresh(req)
        assert result is True
        assert req.status == "pending"

    def test_reset_to_pending_B_not_failed(self, db, svc):
        """B: pending 상태는 리셋 불가 → False."""
        req = svc.enqueue("ct", "ci5", "prompt")
        result = svc.reset_to_pending(req.id)
        assert result is False
