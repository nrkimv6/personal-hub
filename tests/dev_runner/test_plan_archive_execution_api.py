from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.modules.dev_runner.routes.plan_records import (
    list_archive_execution_history,
    run_archive_executions,
    sync_archive_executions,
)
from app.modules.dev_runner.schemas import PlanArchiveExecutionRunRequest, PlanArchiveSelectedProfile


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


def test_run_archive_executions_queues_selected_record(db):
    record = PlanRecord(
        filename_hash="hash-api",
        file_path="/archive/2026-05-06_api.md",
        raw_content="# api",
        archived_at=datetime(2026, 5, 6),
        llm_processed_at=None,
    )
    db.add(record)
    db.commit()
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        result = run_archive_executions(
            PlanArchiveExecutionRunRequest(
                record_ids=[record.id],
                selected_profiles=[PlanArchiveSelectedProfile(engine="claude", profile_name="work")],
            ),
            db=db,
        )

    assert result["queued"] == 1
    assert result["profile_count"] == 1
    assert len(result["request_ids"]) == 1


def test_sync_and_history_endpoints_return_wrapper_shape(db):
    sync_result = sync_archive_executions(db=db)
    history = list_archive_execution_history(limit=10, db=db)

    assert sync_result["checked"] == 0
    assert history["items"] == []
    assert history["total"] == 0
    assert history["limit"] == 10
