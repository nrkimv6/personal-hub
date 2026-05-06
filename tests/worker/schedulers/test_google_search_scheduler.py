"""Focused GoogleSearchScheduler contract tests."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm.exc import DetachedInstanceError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.task_schedule import TaskSchedule
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
    TaskSchedule.__table__.create(bind=engine, checkfirst=True)
    GoogleSavedSearch.__table__.create(bind=engine, checkfirst=True)
    GoogleSearchQueue.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, expire_on_commit=True)
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
    # execute() must use ClaimedRun.target_config_snapshot because real schedules
    # can be detached after claim_run commits and the dispatch session closes.
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
            ClaimedRun(
                run=MagicMock(id=3),
                schedule_id=5,
                task_name="google_schedule_5_run_3",
                target_config_snapshot={"saved_search_id": saved_search_id},
            ),
            ctx,
        )

    assert outcome.stop_reason == "search_queued"
    assert "search_id" in outcome.config_snapshot_patch

    with session_factory() as db:
        queue_item = db.query(GoogleSearchQueue).one()

    assert queue_item.schedule_id == 5
    assert queue_item.saved_search_id == saved_search_id


@pytest.mark.asyncio
async def test_execute_error_missing_saved_search_id_from_snapshot(session_factory):
    scheduler = GoogleSearchScheduler()
    ctx = WorkerContext(
        worker_name="test_worker",
        browser_manager=None,
        db_factory=session_factory,
        update_worker_state=MagicMock(),
    )

    with pytest.raises(RuntimeError, match="saved_search_id 없음"):
        await scheduler.execute(
            MagicMock(id=5),
            ClaimedRun(
                run=MagicMock(id=3),
                schedule_id=5,
                task_name="google_schedule_5_run_3",
                target_config_snapshot={},
            ),
            ctx,
        )


@pytest.mark.asyncio
async def test_execute_boundary_detached_schedule_not_accessed(session_factory):
    with session_factory() as db:
        saved_search = GoogleSavedSearch(
            name="Detached",
            query="detached query",
            date_filter="1w",
            max_pages=1,
        )
        db.add(saved_search)
        db.commit()
        db.refresh(saved_search)
        saved_search_id = saved_search.id

        schedule = TaskSchedule(
            name="google-detached",
            display_name="Google Detached",
            target_type=TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH,
            schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
            schedule_value="0 2 * * *",
            enabled=True,
        )
        schedule.set_target_config({"saved_search_id": saved_search_id})
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        schedule_id = schedule.id
        db.commit()

    with pytest.raises(DetachedInstanceError):
        schedule.get_target_config()

    scheduler = GoogleSearchScheduler()
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
            ClaimedRun(
                run=MagicMock(id=3),
                schedule_id=schedule_id,
                task_name=f"google_schedule_{schedule_id}_run_3",
                target_config_snapshot={"saved_search_id": saved_search_id},
            ),
            ctx,
        )

    assert outcome.stop_reason == "search_queued"
    with session_factory() as db:
        queue_item = db.query(GoogleSearchQueue).one()

    assert queue_item.schedule_id == schedule_id
