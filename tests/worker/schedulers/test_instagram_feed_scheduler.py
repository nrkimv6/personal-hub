"""Focused InstagramFeedScheduler contract tests."""

import json
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import TaskSchedule, TaskScheduleRun
from app.modules.instagram.models.schemas import TimeWindow
from app.modules.instagram.schedulers.feed_schedule import InstagramFeedScheduler
from app.modules.instagram.services.scheduler import InstagramScheduler
from app.services.schedule_contracts import build_time_window_candidate_summary
from app.services.task_schedule_service import TaskScheduleService
from app.worker.schedule_handler_base import ClaimedRun, ScheduleExecutionSpec, WorkerContext


def _sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    TaskSchedule.__table__.create(engine)
    TaskScheduleRun.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _create_instagram_schedule(db, windows: list[dict[str, str]] | None = None) -> TaskSchedule:
    schedule = TaskSchedule(
        name="instagram_feed_account_6",
        target_type=TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
        enabled=True,
        schedule_value=json.dumps(
            {
                "daily_runs": len(windows or [{"start": "09:00", "end": "12:00"}]),
                "time_windows": windows or [{"start": "09:00", "end": "12:00"}],
            }
        ),
    )
    schedule.set_target_config({"service_account_id": 6, "min_interval_hours": 2})
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


def test_exact_slot_schedule_returns_empty_and_requires_repair():
    scheduler = InstagramScheduler(
        daily_runs=8,
        time_windows=[
            TimeWindow(start="07:00", end="07:00"),
            TimeWindow(start="09:20", end="09:20"),
        ],
    )

    assert scheduler.generate_daily_schedule(date(2026, 5, 4)) == []

    summary = build_time_window_candidate_summary(
        {
            "daily_runs": 8,
            "time_windows": [
                {"start": "07:00", "end": "07:00"},
                {"start": "09:20", "end": "09:20"},
            ],
        },
        start_date=date(2026, 5, 4),
    )
    assert summary["health"] == "error"
    assert summary["reason"] == "exact_time_window_zero_candidates"
    assert summary["candidate_count"] == 0


def test_claim_run_R_runs_due_slot_even_when_last_run_was_recent(monkeypatch):
    scheduler = InstagramFeedScheduler()
    schedule = MagicMock(spec=TaskSchedule)
    schedule.id = 7
    schedule.schedule_value = json.dumps(
        {"daily_runs": 1, "time_windows": [{"start": "09:00", "end": "12:00"}]}
    )
    schedule.get_target_config.return_value = {"service_account_id": 6, "min_interval_hours": 2}
    svc = MagicMock()
    svc.get_oldest_deferred_run.return_value = None
    svc.get_latest_run.return_value = MagicMock(started_at=datetime(2026, 5, 3, 9, 59, 55))
    svc.has_active_run.return_value = False
    svc.is_slot_claimed.return_value = False
    svc.start_run.return_value = MagicMock(id=11)
    ctx = WorkerContext(
        worker_name="test_worker",
        browser_manager=None,
        db_factory=MagicMock(),
        now=datetime(2026, 5, 3, 10, 0),
    )
    due_run_time = datetime(2026, 5, 3, 10, 0)

    def fake_due(self, **kwargs):
        assert kwargs.get("min_interval_hours") is None
        return due_run_time

    monkeypatch.setattr(
        "app.modules.instagram.schedulers.feed_schedule.InstagramScheduler.get_due_run_time",
        fake_due,
    )

    claimed = scheduler.claim_run(MagicMock(), schedule, svc, ctx)

    assert claimed is not None
    svc.start_run.assert_called_once()
    snapshot = svc.start_run.call_args.kwargs["config_snapshot"]
    assert snapshot["scheduled_for"] == due_run_time.isoformat()
    assert snapshot["schedule_params"]["time_windows"] == [{"start": "09:00", "end": "12:00"}]


def test_claim_run_C_active_run_defers_due_slot_instead_of_dropping(monkeypatch):
    db = _sqlite_session()
    try:
        schedule = _create_instagram_schedule(db)
        svc = TaskScheduleService(db)
        svc.start_run(schedule.id, worker_id="scheduled_worker")
        due_run_time = datetime(2026, 5, 4, 10, 0)
        monkeypatch.setattr(
            "app.modules.instagram.schedulers.feed_schedule.InstagramScheduler.get_due_run_time",
            lambda self, **kwargs: due_run_time,
        )

        claimed = InstagramFeedScheduler().claim_run(
            db,
            schedule,
            svc,
            WorkerContext(
                worker_name="scheduled_worker",
                browser_manager=None,
                db_factory=MagicMock(),
                now=due_run_time,
            ),
        )

        assert claimed is None
        deferred = db.query(TaskScheduleRun).filter_by(status=TaskScheduleRun.STATUS_DEFERRED).one()
        assert deferred.get_config_snapshot()["scheduled_for"] == due_run_time.isoformat()
    finally:
        db.close()


def test_claim_run_O_deferred_slot_runs_after_active_run_finishes():
    db = _sqlite_session()
    try:
        schedule = _create_instagram_schedule(db)
        svc = TaskScheduleService(db)
        due_run_time = datetime(2026, 5, 4, 10, 0)
        deferred = svc.get_or_create_deferred_run(
            schedule_id=schedule.id,
            scheduled_for=due_run_time,
            config_snapshot={"scheduled_for": due_run_time.isoformat()},
        )

        claimed = InstagramFeedScheduler().claim_run(
            db,
            schedule,
            svc,
            WorkerContext(
                worker_name="scheduled_worker",
                browser_manager=None,
                db_factory=MagicMock(),
                now=due_run_time + timedelta(minutes=30),
            ),
        )

        assert claimed is not None
        assert claimed.run_id == deferred.id
        db.refresh(deferred)
        assert deferred.status == TaskScheduleRun.STATUS_RUNNING
        assert deferred.worker_id == "scheduled_worker"
        assert deferred.get_config_snapshot()["scheduled_for"] == due_run_time.isoformat()
    finally:
        db.close()


def test_claim_run_Ca_does_not_duplicate_same_scheduled_for(monkeypatch):
    db = _sqlite_session()
    try:
        schedule = _create_instagram_schedule(db)
        svc = TaskScheduleService(db)
        due_run_time = datetime(2026, 5, 4, 10, 0)
        svc.start_run(
            schedule.id,
            worker_id="scheduled_worker",
            config_snapshot={"scheduled_for": due_run_time.isoformat()},
        )
        monkeypatch.setattr(
            "app.modules.instagram.schedulers.feed_schedule.InstagramScheduler.get_due_run_time",
            lambda self, **kwargs: due_run_time,
        )

        claimed = InstagramFeedScheduler().claim_run(
            db,
            schedule,
            svc,
            WorkerContext(
                worker_name="scheduled_worker",
                browser_manager=None,
                db_factory=MagicMock(),
                now=due_run_time,
            ),
        )

        assert claimed is None
        assert db.query(TaskScheduleRun).count() == 1
    finally:
        db.close()


@pytest.mark.asyncio
async def test_execute_requires_execute_with_tab_context():
    scheduler = InstagramFeedScheduler()
    ctx = WorkerContext(worker_name="test_worker", browser_manager=None, db_factory=MagicMock())

    with pytest.raises(RuntimeError, match="execute_with_tab"):
        await scheduler.execute(
            ScheduleExecutionSpec(
                schedule_id=1,
                target_type=TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
                name="instagram",
                target_config={"service_account_id": 7},
                schedule_value=None,
                schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
                display_name="Instagram",
            ),
            ClaimedRun(run_id=2, schedule_id=1, task_name="instagram_schedule_1_run_2"),
            ctx,
        )


@pytest.mark.asyncio
async def test_crawl_feed_with_tab_reuses_claimed_schedule_run(monkeypatch):
    scheduler = InstagramFeedScheduler()
    tab = AsyncMock()
    tab.url = "https://www.instagram.com/"
    account = MagicMock(id=6, identifier="account_6")
    run = MagicMock(id=22)
    crawl_run = MagicMock(
        status=TaskScheduleRun.STATUS_COMPLETED,
        collected_count=10,
        saved_count=4,
        stop_reason="completed",
    )
    crawl_service = MagicMock()
    crawl_service.run_crawl = AsyncMock(return_value=crawl_run)
    ctx = WorkerContext(worker_name="scheduled_worker", browser_manager=None, db_factory=MagicMock())
    monkeypatch.setattr(scheduler, "_is_logged_in", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "app.modules.instagram.schedulers.feed_schedule.InstagramCrawler",
        lambda page: "crawler",
    )

    outcome = await scheduler._crawl_feed_with_tab(
        tab,
        MagicMock(),
        run,
        account,
        MagicMock(),
        crawl_service,
        ctx,
    )

    crawl_service.run_crawl.assert_awaited_once_with(
        crawler="crawler",
        service_account_id=6,
        schedule_run_id=22,
    )
    assert outcome.collected_count == 10
    assert outcome.saved_count == 4


@pytest.mark.asyncio
async def test_is_logged_in_distinguishes_logged_out_and_logged_in_pages():
    scheduler = InstagramFeedScheduler()

    logged_out_page = MagicMock()
    logged_out_page.query_selector = AsyncMock(side_effect=[object()])
    assert await scheduler._is_logged_in(logged_out_page) is False

    logged_in_page = MagicMock()
    logged_in_page.query_selector = AsyncMock(side_effect=[None, None, None, None, object()])
    assert await scheduler._is_logged_in(logged_in_page) is True
