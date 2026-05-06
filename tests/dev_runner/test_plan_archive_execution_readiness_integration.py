from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.plan_archive_execution import (
    PlanArchiveExecutionAttempt,
    PlanArchiveExecutionJob,
)
from app.models.plan_record import PlanEvent, PlanRecord
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.modules.claude_worker.models.llm_request import (
    LLMProfileAssignment,
    LLMRequest,
    LLMRequestProfileClaim,
    LLMScheduleProfilePolicy,
)
from app.modules.dev_runner.routes.plan_records import (
    get_archive_health,
    run_archive_executions,
)
from app.modules.dev_runner.schemas import PlanArchiveExecutionRunRequest


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _create_required_runtime_tables(db, *, include_policy: bool) -> None:
    tables = [
        PlanRecord.__table__,
        PlanEvent.__table__,
        TaskSchedule.__table__,
        TaskScheduleRun.__table__,
        LLMRequest.__table__,
        PlanArchiveExecutionJob.__table__,
        PlanArchiveExecutionAttempt.__table__,
        LLMRequestProfileClaim.__table__,
        LLMProfileAssignment.__table__,
    ]
    if include_policy:
        tables.append(LLMScheduleProfilePolicy.__table__)
    Base.metadata.create_all(bind=db.get_bind(), tables=tables)


def _seed_record(db) -> PlanRecord:
    record = PlanRecord(
        filename_hash="hash-readiness-run",
        file_path="/archive/2026-05-06_readiness-run.md",
        raw_content="# readiness run",
        archived_at=datetime(2026, 5, 6),
        llm_processed_at=None,
    )
    db.add(record)
    db.commit()
    return record


def test_missing_policy_table_run_returns_503_and_creates_no_requests(db):
    _create_required_runtime_tables(db, include_policy=False)
    record = _seed_record(db)

    with pytest.raises(HTTPException) as exc:
        run_archive_executions(
            PlanArchiveExecutionRunRequest(record_ids=[record.id]),
            db=db,
        )

    assert exc.value.status_code == 503
    detail = exc.value.detail
    assert detail["execution_db_readiness"]["ok"] is False
    assert detail["missing_tables"] == ["llm_schedule_profile_policies"]
    assert db.query(LLMRequest).count() == 0
    assert db.query(PlanArchiveExecutionJob).count() == 0


def test_readiness_ok_run_queues_existing_flow(db):
    _create_required_runtime_tables(db, include_policy=True)
    record = _seed_record(db)
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        result = run_archive_executions(
            PlanArchiveExecutionRunRequest(record_ids=[record.id]),
            db=db,
        )

    assert result["queued"] == 1
    assert db.query(LLMRequest).count() == 1
    assert db.query(PlanArchiveExecutionJob).count() == 1


def test_archive_health_execution_missing_tables_matches_repro(db):
    _create_required_runtime_tables(db, include_policy=False)
    _seed_record(db)

    health = get_archive_health(db=db)

    assert health["execution_db_readiness"]["ok"] is False
    assert health["execution_db_readiness"]["missing_tables"] == ["llm_schedule_profile_policies"]
