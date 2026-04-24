"""Focused GoogleSearchScheduler contract tests."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.google_search import GoogleSavedSearch, GoogleSearchQueue
from app.modules.google_search.schedulers.search_schedule import GoogleSearchScheduler
from app.worker.schedule_handler_base import ClaimedRun, WorkerContext


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    GoogleSavedSearch.__table__.create(bind=engine, checkfirst=True)
    GoogleSearchQueue.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()


@pytest.mark.asyncio
async def test_execute_returns_search_queued_stop_reason(session_factory):
    with session_factory() as db:
        saved_search = GoogleSavedSearch(
            name="Search",
            query="site:example.com",
            date_filter="1w",
            max_pages=1,
            search_params=json.dumps({"lr": "lang_ko"}),
        )
        db.add(saved_search)
        db.commit()
        db.refresh(saved_search)
        saved_search_id = saved_search.id

    scheduler = GoogleSearchScheduler()
    schedule = MagicMock(id=5)
    schedule.get_target_config.return_value = {"saved_search_id": saved_search_id}
    ctx = WorkerContext(
        worker_name="test_worker",
        browser_manager=None,
        db_factory=session_factory,
        update_worker_state=MagicMock(),
    )

    with patch(
        "app.modules.google_search.schedulers.search_schedule.enqueue_google_search",
        AsyncMock(return_value=GoogleSearchQueue.STATUS_QUEUED),
    ):
        outcome = await scheduler.execute(
            schedule,
            ClaimedRun(run=MagicMock(id=3), task_name="google_schedule_5_run_3"),
            ctx,
        )

    assert outcome.stop_reason == "search_queued"
    assert "search_id" in outcome.config_snapshot_patch
