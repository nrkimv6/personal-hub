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


def test_history_contains_failed_and_completed_attempt_statuses(db):
    records = [
        PlanRecord(filename_hash="hash-ok", file_path="/archive/ok.md", raw_content="# ok", archived_at=datetime(2026, 5, 6)),
        PlanRecord(filename_hash="hash-fail", file_path="/archive/fail.md", raw_content="# fail", archived_at=datetime(2026, 5, 6)),
    ]
    db.add_all(records)
    db.commit()
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")
    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        PlanArchiveExecutionService(db).enqueue_records(records, trigger_source="manual:plan_archive_analyze")
        db.commit()

    requests = db.query(LLMRequest).order_by(LLMRequest.id.asc()).all()
    requests[0].status = "completed"
    requests[0].processed_at = datetime(2026, 5, 6, 12, 0)
    requests[1].status = "failed"
    requests[1].error_message = "quota"
    requests[1].processed_at = datetime(2026, 5, 6, 12, 1)
    db.commit()

    service = PlanArchiveExecutionService(db)
    for request in requests:
        service.sync_attempt_for_request_id(request.id)

    statuses = {item["status"] for item in service.history(limit=10)}
    assert statuses == {"completed", "failed"}
