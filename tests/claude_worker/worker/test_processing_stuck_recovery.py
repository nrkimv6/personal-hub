"""Regression tests for processing requests that fail inside a dirty DB session."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest, LLMRequestProfileClaim
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.worker import worker as worker_mod


class _RollbackTrackingDb:
    def __init__(self):
        self.rollback_count = 0

    def rollback(self):
        self.rollback_count += 1


class _FallbackDb:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_mark_request_failed_safely_rolls_back_before_mark_failed():
    calls = []

    class Service:
        def mark_failed(self, request_id, error_message, raw_response=""):
            calls.append((request_id, error_message, raw_response))

    db = _RollbackTrackingDb()
    worker = worker_mod.LLMWorker()

    worker._mark_request_failed_safely(Service(), db, 15435, "profile table missing", "raw")

    assert db.rollback_count == 1
    assert calls == [(15435, "profile table missing", "raw")]


def test_mark_request_failed_safely_uses_fallback_session_after_failed_mark(monkeypatch):
    db = _RollbackTrackingDb()
    fallback_db = _FallbackDb()
    fallback_calls = []

    class BrokenService:
        def mark_failed(self, request_id, error_message, raw_response=""):
            raise RuntimeError("pending rollback")

    class FallbackService:
        def __init__(self, session):
            assert session is fallback_db

        def mark_failed(self, request_id, error_message, raw_response=""):
            fallback_calls.append((request_id, error_message, raw_response))

    monkeypatch.setattr(worker_mod, "SessionLocal", lambda: fallback_db)
    monkeypatch.setattr(worker_mod, "LLMService", FallbackService)

    worker = worker_mod.LLMWorker()
    worker._mark_request_failed_safely(BrokenService(), db, 15436, "claim failed")

    assert db.rollback_count == 2
    assert fallback_calls == [(15436, "claim failed", "")]
    assert fallback_db.closed is True


class _FakeRequest:
    def __init__(self, request_id=15435, caller_type="test"):
        self.id = request_id
        self.caller_type = caller_type
        self.caller_id = "caller-1"
        self.queue_name = "utility"
        self.cli_options = None
        self.provider = "claude"
        self.model = "claude-opus-4-6"
        self.prompt = "prompt"


class _IdExpiresAfterCaptureRequest(_FakeRequest):
    def __init__(self):
        super().__init__(request_id=15436)
        self._id_reads = 0

    @property
    def id(self):
        self._id_reads += 1
        if self._id_reads > 1:
            raise AssertionError("request.id was read after identity capture")
        return 15436

    @id.setter
    def id(self, value):
        self._request_id = value


class _ExecuteService:
    def __init__(self, *, execute_error=None, execute_result=None):
        self.execute_error = execute_error
        self.execute_result = execute_result
        self.status_by_id = {}
        self.failed = []
        self.completed = []

    def mark_processing(self, request_id):
        self.status_by_id[request_id] = "processing"

    def resolve_provider_model(self, caller_type, provider=None, model=None):
        return provider or "claude", model or "claude-opus-4-6"

    def execute_llm(self, **kwargs):
        if self.execute_error:
            raise self.execute_error
        if self.execute_result is not None:
            return self.execute_result
        return {"success": False, "error": "executor failed"}

    def mark_completed(self, request_id, result, raw_response, claude_session_id=None):
        self.status_by_id[request_id] = "completed"
        self.completed.append((request_id, result, raw_response, claude_session_id))

    def mark_failed(self, request_id, error_message, raw_response=""):
        self.status_by_id[request_id] = "failed"
        self.failed.append((request_id, error_message, raw_response))


@pytest.mark.asyncio
async def test_execute_request_exception_after_processing_E_no_processing_stuck(monkeypatch):
    monkeypatch.setattr(worker_mod.provider_registry, "get_quota_providers", lambda: [])
    service = _ExecuteService(execute_error=RuntimeError("executor crashed"))
    db = _RollbackTrackingDb()
    worker = worker_mod.LLMWorker()

    await worker._execute_request(_FakeRequest(), db, service)

    assert service.status_by_id[15435] == "failed"
    assert service.failed[0][0] == 15435
    assert "executor crashed" in service.failed[0][1]


@pytest.mark.asyncio
async def test_execute_request_failed_finalizer_B_uses_captured_request_id(monkeypatch):
    monkeypatch.setattr(worker_mod.provider_registry, "get_quota_providers", lambda: [])
    service = _ExecuteService(execute_error=RuntimeError("after capture"))
    db = _RollbackTrackingDb()
    worker = worker_mod.LLMWorker()

    await worker._execute_request(_IdExpiresAfterCaptureRequest(), db, service)

    assert service.status_by_id[15436] == "failed"
    assert service.failed[0][0] == 15436


@pytest.mark.asyncio
async def test_execute_request_profile_claim_db_error_E_marks_failed(monkeypatch):
    service = _ExecuteService()
    db = _RollbackTrackingDb()
    worker = worker_mod.LLMWorker()

    monkeypatch.setattr(worker_mod.provider_registry, "get_quota_providers", lambda: ["claude"])

    class Router:
        def __init__(self, session):
            pass

        def select_profile(self, provider, model, request):
            return SimpleNamespace(
                profile=SimpleNamespace(name="profile-a", capacity=1),
                reason=None,
                next_available_at=None,
                blocked_counts={},
            )

    class ClaimService:
        def __init__(self, session):
            pass

        def claim(self, request_id, engine, profile_name, **kwargs):
            raise RuntimeError("relation llm_profile_assignments does not exist")

    import app.modules.claude_worker.services.profile_router as profile_router
    import app.modules.claude_worker.services.profile_claim_service as profile_claim_service

    monkeypatch.setattr(profile_router, "LLMProfileRouter", Router)
    monkeypatch.setattr(profile_claim_service, "ProfileClaimService", ClaimService)

    await worker._execute_request(_FakeRequest(caller_type="plan_archive_analyze"), db, service)

    assert service.status_by_id[15435] == "failed"
    assert "llm_profile_assignments" in service.failed[0][1]


@pytest.mark.asyncio
async def test_plan_archive_stale_save_outcome_R_keeps_request_completed(monkeypatch):
    monkeypatch.setattr(worker_mod.provider_registry, "get_quota_providers", lambda: [])
    monkeypatch.setattr(
        worker_mod,
        "save_plan_archive_result_outcome",
        lambda db, request, result: SimpleNamespace(
            saved=False,
            status="stale_skipped",
            reason="newer_completed_result_exists",
            record_id=42,
        ),
    )
    service = _ExecuteService(
        execute_result={
            "success": True,
            "result": {"category": "old"},
            "raw_response": '{"category": "old"}',
            "claude_session_id": "session-stale",
        }
    )
    db = _RollbackTrackingDb()
    worker = worker_mod.LLMWorker()

    await worker._execute_request(_FakeRequest(caller_type="plan_archive_analyze"), db, service)

    assert service.status_by_id[15435] == "completed"
    assert service.completed == [
        (15435, {"category": "old"}, '{"category": "old"}', "session-stale")
    ]
    assert service.failed == []


def test_execute_request_real_session_rollback_E_marks_failed():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        request = LLMRequest(
            caller_type="plan_archive_analyze",
            caller_id="archive-1",
            prompt="prompt",
            status="processing",
            requested_at=datetime.now(),
        )
        db.add(request)
        db.commit()
        request_id = request.id

        db.add_all([
            LLMRequestProfileClaim(
                request_id=request_id,
                engine="claude",
                profile_name="profile-a",
            ),
            LLMRequestProfileClaim(
                request_id=request_id,
                engine="claude",
                profile_name="profile-b",
            ),
        ])
        with pytest.raises(Exception):
            db.flush()

        worker = worker_mod.LLMWorker()
        worker._mark_request_failed_safely(LLMService(db), db, request_id, "claim failed")
    finally:
        db.close()

    verify_db = Session()
    try:
        refreshed = verify_db.query(LLMRequest).filter(LLMRequest.id == request_id).one()
        assert refreshed.status == "failed"
        assert refreshed.processed_at is not None
        assert refreshed.error_message == "claim failed"
    finally:
        verify_db.close()
        engine.dispose()


def test_execute_request_failed_finalizer_E_logs_and_continues(caplog):
    db = _RollbackTrackingDb()

    class BrokenService:
        def mark_failed(self, request_id, error_message, raw_response=""):
            raise RuntimeError("mark failed unavailable")

    class BrokenFallbackService:
        def __init__(self, session):
            pass

        def mark_failed(self, request_id, error_message, raw_response=""):
            raise RuntimeError("fallback unavailable")

    monkeypatch_context = pytest.MonkeyPatch()
    fallback_db = _FallbackDb()
    monkeypatch_context.setattr(worker_mod, "SessionLocal", lambda: fallback_db)
    monkeypatch_context.setattr(worker_mod, "LLMService", BrokenFallbackService)
    try:
        worker = worker_mod.LLMWorker()
        worker._mark_request_failed_safely(BrokenService(), db, 15437, "boom")
    finally:
        monkeypatch_context.undo()

    assert fallback_db.closed is True
    assert "최종 fallback 실패" in caplog.text
