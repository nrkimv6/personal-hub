from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.services.plan_archive_execution_service import PlanArchiveExecutionService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _enqueue(db, record):
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")
    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        PlanArchiveExecutionService(db).enqueue_records([record], trigger_source="manual:plan_archive_analyze")
        db.commit()


def test_sync_recovers_job_state_from_llm_request(db):
    record = PlanRecord(
        filename_hash="hash-sync",
        file_path="/archive/2026-05-06_sync.md",
        raw_content="# sync",
        archived_at=datetime(2026, 5, 6),
        llm_processed_at=None,
    )
    db.add(record)
    db.commit()
    _enqueue(db, record)
    request = db.query(LLMRequest).one()
    request.status = "completed"
    request.processed_at = datetime(2026, 5, 6, 12, 0)
    db.commit()

    result = PlanArchiveExecutionService(db).sync()
    history = PlanArchiveExecutionService(db).history(record_id=record.id)

    assert result["updated"] == 1
    assert history[0]["status"] == "completed"


def test_completed_record_is_not_manual_run_target(db):
    record = PlanRecord(
        filename_hash="hash-done",
        file_path="/archive/2026-05-06_done.md",
        raw_content="# done",
        archived_at=datetime(2026, 5, 6),
        llm_processed_at=datetime(2026, 5, 6, 12, 0),
    )
    db.add(record)
    db.commit()

    result = PlanArchiveExecutionService(db).enqueue_unprocessed(
        include_temp_records=False,
        max_backfill_per_run=10,
    )

    assert result["queued"] == 0
    assert db.query(LLMRequest).count() == 0
