import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.plan_archive_execution import PlanArchiveExecutionAttempt, PlanArchiveExecutionJob
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMProfileAssignment, LLMRequest
from app.modules.dev_runner.services.plan_archive_execution_service import PlanArchiveExecutionService


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _record(**kwargs):
    defaults = {
        "filename_hash": "hash-1",
        "file_path": "/archive/2026-05-06_plan.md",
        "raw_content": "# plan\nbody",
        "archived_at": datetime(2026, 5, 6),
        "llm_processed_at": None,
    }
    defaults.update(kwargs)
    return PlanRecord(**defaults)


def test_enqueue_record_creates_job_attempt_and_candidate_profile_snapshot(db):
    record = _record()
    db.add(record)
    db.commit()
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        result = PlanArchiveExecutionService(db).enqueue_records(
            [record],
            trigger_source="manual:plan_archive_analyze",
            selected_profiles=[{"engine": "claude", "profile_name": "work"}],
            requested_by="api",
        )
        db.commit()

    assert result["queued"] == 1
    job = db.query(PlanArchiveExecutionJob).one()
    attempt = db.query(PlanArchiveExecutionAttempt).one()
    request = db.query(LLMRequest).one()
    assert job.plan_record_id == record.id
    assert job.status == "queued"
    assert job.selected_profiles == [{"engine": "claude", "profile_name": "work"}]
    assert attempt.job_id == job.id
    assert attempt.llm_request_id == request.id
    options = json.loads(request.cli_options)
    assert options["plan_archive_execution_job_id"] == job.id
    assert options["candidate_profiles"] == [{"engine": "claude", "profile_name": "work"}]


def test_enqueue_record_skips_duplicate_active_request(db):
    record = _record(filename_hash="hash-active")
    db.add(record)
    db.add(
        LLMRequest(
            caller_type="plan_archive_analyze",
            caller_id="hash-active",
            prompt="existing",
            status="pending",
        )
    )
    db.commit()

    result = PlanArchiveExecutionService(db).enqueue_records(
        [record],
        trigger_source="manual:plan_archive_analyze",
    )

    assert result["queued"] == 0
    assert result["skipped_active_request"] == 1
    assert db.query(PlanArchiveExecutionJob).count() == 0


def test_sync_attempt_and_history_include_profile_assignment(db):
    record = _record(filename_hash="hash-history")
    db.add(record)
    db.commit()
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")
    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        PlanArchiveExecutionService(db).enqueue_records(
            [record],
            trigger_source="schedule:plan_archive_analyze",
        )
        db.commit()

    request = db.query(LLMRequest).one()
    request.status = "completed"
    request.processed_at = datetime(2026, 5, 6, 12, 0)
    db.add(
        LLMProfileAssignment(
            request_id=request.id,
            engine="claude",
            profile_name="work",
            selected_at=datetime(2026, 5, 6, 11, 59),
        )
    )
    db.commit()

    service = PlanArchiveExecutionService(db)
    assert service.sync_attempt_for_request_id(request.id) is True
    history = service.history(record_id=record.id)

    assert history[0]["status"] == "completed"
    assert history[0]["record_id"] == record.id
    assert history[0]["engine"] == "claude"
    assert history[0]["profile_name"] == "work"
