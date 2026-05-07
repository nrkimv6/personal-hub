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
        assert req.processed_at is not None

    def test_mark_completed_R_stores_result(self, db, svc):
        """R: mark_completed → result 저장."""
        req = svc.enqueue("ct", "ci2", "prompt")
        svc.mark_completed(req.id, {"key": "val"}, raw_response="raw")
        db.refresh(req)
        assert req.status == "completed"
        assert req.processed_at is not None

    def test_prepare_completed_R_sets_fields_without_commit(self, db, svc):
        """R: prepare_completed는 상태 필드만 채우고 commit은 호출자가 결정."""
        req = svc.enqueue("ct", "ci2b", "prompt")
        original_commit = db.commit
        db.commit = MagicMock(side_effect=original_commit)
        svc.prepare_completed(req.id, {"key": "val"}, raw_response="raw")

        assert db.commit.call_count == 0
        original_commit()
        db.refresh(req)
        assert req.status == "completed"
        assert req.raw_response == "raw"

    def test_mark_failed_R_increments_retry(self, db, svc):
        """R: mark_failed → retry_count 증가."""
        req = svc.enqueue("ct", "ci3", "prompt")
        initial = req.retry_count
        svc.mark_failed(req.id, "some error")
        db.refresh(req)
        assert req.status == "failed"
        assert req.retry_count == initial + 1

    def test_mark_failed_R_classifies_gemini_runtime_errors(self, db, svc):
        """R: Gemini CLI readiness/auth 오류는 failure_category에 분리 저장된다."""
        missing = svc.enqueue("ct", "gemini-missing", "prompt")
        auth = svc.enqueue("ct", "gemini-auth", "prompt")
        generic = svc.enqueue("ct", "gemini-error", "prompt")

        svc.mark_failed(missing.id, "Gemini CLI not found. Searched: gemini.cmd")
        svc.mark_failed(auth.id, "Gemini CLI authentication required: please log in")
        svc.mark_failed(generic.id, "Gemini CLI error: bad arg")

        db.refresh(missing)
        db.refresh(auth)
        db.refresh(generic)
        assert missing.failure_category == "gemini_cli_not_found"
        assert auth.failure_category == "gemini_auth_required"
        assert generic.failure_category == "gemini_cli_error"

    def test_mark_failed_R_handles_null_retry_count(self, db, svc):
        """R: legacy retry_count NULL row도 failed 전이가 가능하다."""
        req = svc.enqueue("ct", "ci3-null-retry", "prompt")
        req.retry_count = None
        db.commit()

        svc.mark_failed(req.id, "some error")

        db.refresh(req)
        assert req.status == "failed"
        assert req.retry_count == 1

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

    def test_reset_to_pending_R_from_processing_preserves_block_reason(self, db, svc):
        """R: router가 processing을 pending으로 되돌릴 때 보류 사유를 보존."""
        req = svc.enqueue("ct", "ci6", "prompt")
        svc.mark_processing(req.id)

        result = svc.reset_to_pending(req.id, "schedule_policy_off")

        db.refresh(req)
        assert result is True
        assert req.status == "pending"
        assert req.error_message == "schedule_policy_off"

        from app.modules.claude_worker.routes.llm_schemas import _to_response

        response = _to_response(req)
        assert response.pending_block_reason == "schedule_policy_off"
