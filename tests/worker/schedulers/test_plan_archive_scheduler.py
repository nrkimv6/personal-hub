"""Focused PlanArchiveScheduler contract tests."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.schedulers.plan_archive_schedule import PlanArchiveScheduler
from app.worker.schedule_handler_base import ClaimedRun, WorkerContext


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


def _make_ctx(session_factory):
    return WorkerContext(worker_name="test_worker", browser_manager=None, db_factory=session_factory)


@pytest.mark.asyncio
async def test_execute_propagates_queue_failures(session_factory):
    scheduler = PlanArchiveScheduler()

    with patch.object(PlanArchiveScheduler, "_enqueue_unprocessed_plans", side_effect=RuntimeError("queue failed")):
        with pytest.raises(RuntimeError, match="queue failed"):
            await scheduler.execute(
                MagicMock(id=1),
                ClaimedRun(run=MagicMock(id=3), task_name="plan_archive_1_run_3"),
                _make_ctx(session_factory),
            )


def test_enqueue_unprocessed_plans_uses_db_first_content(session_factory):
    with session_factory() as db:
        db.add(
            PlanRecord(
                filename_hash="db-first-hash",
                file_path="/archive/2026-04-24_plan.md",
                raw_content="# stored\ncontent",
                archived_at=datetime(2026, 4, 24),
                llm_processed_at=None,
            )
        )
        db.commit()

    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch("app.modules.dev_runner.schedulers.plan_archive_schedule.LLMService", return_value=fake_llm), patch(
        "app.modules.dev_runner.schedulers.plan_archive_schedule.build_plan_analyze_prompt",
        side_effect=lambda file_content, filename: f"{filename}:{file_content}",
    ):
        count = PlanArchiveScheduler._enqueue_unprocessed_plans(session_factory)

    assert count == 1
