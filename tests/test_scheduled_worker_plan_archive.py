"""PlanArchiveScheduler raw-content and skip behavior tests."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.schedulers.plan_archive_schedule import PlanArchiveScheduler


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    LLMRequest.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()


def _add_plan_record(session, file_path, raw_content=None):
    record = PlanRecord(
        filename_hash=file_path,
        file_path=file_path,
        raw_content=raw_content,
        archived_at=datetime(2026, 1, 1),
        llm_processed_at=None,
    )
    session.add(record)
    session.commit()
    return record


def test_enqueue_unprocessed_plans_uses_db_raw_content(session_factory):
    with session_factory() as db:
        _add_plan_record(db, "/archive/2026-02-01_plan.md", raw_content="# DB 내용\n파일 없이 처리됨")

    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch(
        "app.modules.dev_runner.schedulers.plan_archive_schedule.LLMService",
        return_value=fake_llm,
    ), patch(
        "app.modules.dev_runner.schedulers.plan_archive_schedule.build_plan_analyze_prompt",
        side_effect=lambda file_content, filename: f"{filename}::{file_content}",
    ):
        count = PlanArchiveScheduler._enqueue_unprocessed_plans(session_factory)

    assert count == 1
    with session_factory() as db:
        req = db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").first()
        assert req is not None
        assert "파일 없이 처리됨" in req.prompt


def test_enqueue_unprocessed_plans_skips_when_content_empty(session_factory):
    with session_factory() as db:
        _add_plan_record(db, "/nonexistent/2026-02-02_gone.md", raw_content=None)

    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch(
        "app.modules.dev_runner.schedulers.plan_archive_schedule.LLMService",
        return_value=fake_llm,
    ):
        count = PlanArchiveScheduler._enqueue_unprocessed_plans(session_factory)

    assert count == 0
    with session_factory() as db:
        assert db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").count() == 0
