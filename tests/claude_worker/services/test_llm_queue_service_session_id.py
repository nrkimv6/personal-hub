"""LLMQueueService claude_session_id 저장 TC (Phase T1)."""

import pytest
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


class TestMarkCompletedSessionId:
    def test_mark_completed_saves_claude_session_id(self, db, svc):
        """R: claude_session_id 전달 시 llm_requests.claude_session_id 저장."""
        req = svc.enqueue("test_caller", "item_1", "prompt", requested_by="test")
        session_uuid = "2af53fdc-182f-47a1-8424-b2e1e897f19e"

        svc.mark_completed(req.id, "result text", raw_response="", claude_session_id=session_uuid)

        db.refresh(req)
        assert req.claude_session_id == session_uuid
        assert req.status == "completed"

    def test_mark_completed_none_session_id_no_error(self, db, svc):
        """B: claude_session_id=None 전달 시 오류 없음, claude_session_id NULL 유지."""
        req = svc.enqueue("test_caller", "item_2", "prompt", requested_by="test")

        svc.mark_completed(req.id, "result text", raw_response="", claude_session_id=None)

        db.refresh(req)
        assert req.claude_session_id is None
        assert req.status == "completed"

    def test_mark_completed_backward_compat_no_session_id_param(self, db, svc):
        """B: claude_session_id 파라미터 생략 시 오류 없음 (하위 호환)."""
        req = svc.enqueue("test_caller", "item_3", "prompt", requested_by="test")

        svc.mark_completed(req.id, "result text")

        db.refresh(req)
        assert req.status == "completed"
