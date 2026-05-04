"""Focused InstagramFeedScheduler contract tests."""

import json
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import TaskSchedule, TaskScheduleRun
from app.modules.instagram.models.schemas import TimeWindow
from app.modules.instagram.schedulers.feed_schedule import InstagramFeedScheduler
from app.modules.instagram.services.scheduler import InstagramScheduler
from app.services.task_schedule_service import TaskScheduleService
from app.worker.schedule_handler_base import ClaimedRun, WorkerContext


OPERATIONAL_EXACT_SLOTS = ["07:00", "09:20", "10:00", "12:00", "14:00", "15:00", "22:00", "17:00"]


def _operational_windows() -> list[TimeWindow]:
    return [TimeWindow(start=value, end=value) for value in OPERATIONAL_EXACT_SLOTS]


def _legacy_exact_slot_schedule(day: date) -> list[datetime]:
    import hashlib
    import random

    rng = random.Random(int(hashlib.md5(f"instagram_scheduler_{day.isoformat()}".encode()).hexdigest()[:8], 16))
    generated: list[datetime] = []
    for window in _operational_windows():
        start = _to_minutes(window.start)
        end = _to_minutes(window.end)
        if end <= start:
            end += 24 * 60
        minutes = rng.randint(start, end)
        run_date = day
        if minutes >= 24 * 60:
            minutes -= 24 * 60
            run_date = day + timedelta(days=1)
        generated.append(datetime.combine(run_date, time(hour=minutes // 60, minute=minutes % 60)))
    return sorted(generated)


def _to_minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    TaskSchedule.__table__.create(engine)
    TaskScheduleRun.__table__.create(engine)
    return sessionmaker(bind=engine)()


def test_operational_exact_slot_schedule_generates_eight_same_day_slots():
    run_date = datetime(2026, 5, 4).date()
    scheduler = InstagramScheduler(daily_runs=8, time_windows=_operational_windows())

    schedule = scheduler.generate_daily_schedule(run_date)

    assert schedule == [
        datetime(2026, 5, 4, 7, 0),
        datetime(2026, 5, 4, 9, 20),
        datetime(2026, 5, 4, 10, 0),
        datetime(2026, 5, 4, 12, 0),
        datetime(2026, 5, 4, 14, 0),
        datetime(2026, 5, 4, 15, 0),
        datetime(2026, 5, 4, 17, 0),
        datetime(2026, 5, 4, 22, 0),
    ]


def test_get_due_run_time_R_exact_slot_due_within_tolerance():
    scheduler = InstagramScheduler(daily_runs=8, time_windows=_operational_windows())

    due = scheduler.get_due_run_time(
        last_run=datetime(2026, 5, 3, 18, 53),
        now=datetime(2026, 5, 4, 22, 4),
        tolerance_minutes=5,
        min_interval_hours=2,
    )

    assert due == datetime(2026, 5, 4, 22, 0)


def test_get_due_run_time_T_exact_slot_not_due_after_tolerance():
    scheduler = InstagramScheduler(daily_runs=8, time_windows=_operational_windows())

    due = scheduler.get_due_run_time(
        last_run=datetime(2026, 5, 3, 18, 53),
        now=datetime(2026, 5, 4, 22, 9),
        tolerance_minutes=5,
        min_interval_hours=2,
    )

    assert due is None


def test_legacy_exact_slot_bug_Re_would_have_generated_2209():
    assert _legacy_exact_slot_schedule(date(2026, 5, 4))[0] == datetime(2026, 5, 4, 22, 9)


def test_claim_run_records_scheduled_for_snapshot():
    scheduler = InstagramFeedScheduler()
    schedule = MagicMock(spec=TaskSchedule)
    schedule.id = 7
    schedule.schedule_value = json.dumps(
        {
            "daily_runs": 1,
            "time_windows": [{"start": "09:00", "end": "09:00"}],
        }
    )
    schedule.get_target_config.return_value = {
        "service_account_id": 6,
        "min_interval_hours": 0,
    }
    svc = MagicMock()
    svc.get_latest_run.return_value = None
    svc.has_active_run.return_value = False
    svc.start_run.return_value = MagicMock(id=11)
    ctx = WorkerContext(worker_name="test_worker", browser_manager=None, db_factory=MagicMock())

    due_run_time = datetime(2026, 5, 3, 9, 0)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "app.modules.instagram.schedulers.feed_schedule.InstagramScheduler.get_due_run_time",
            lambda self, last_run=None, now=None, min_interval_hours=0: due_run_time,
        )
        claimed = scheduler.claim_run(MagicMock(), schedule, svc, ctx)

    assert claimed is not None
    svc.start_run.assert_called_once()
    snapshot = svc.start_run.call_args.kwargs["config_snapshot"]
    assert snapshot["scheduled_for"] == due_run_time.isoformat()
    assert snapshot["schedule_params"] == {
        "daily_runs": 1,
        "time_windows": [{"start": "09:00", "end": "09:00"}],
        "min_interval_hours": 0,
    }


def test_claim_run_Ca_records_scheduled_for_for_operational_slots():
    db = _sqlite_session()
    try:
        schedule = TaskSchedule(
            name="instagram_feed_account_6",
            target_type=TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            enabled=True,
            schedule_value=json.dumps(
                {
                    "daily_runs": 8,
                    "time_windows": [{"start": value, "end": value} for value in OPERATIONAL_EXACT_SLOTS],
                }
            ),
        )
        schedule.set_target_config({"service_account_id": 6, "min_interval_hours": 2})
        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        svc = TaskScheduleService(db)
        ctx = WorkerContext(
            worker_name="scheduled_worker",
            browser_manager=None,
            db_factory=MagicMock(),
            now=datetime(2026, 5, 4, 22, 4),
        )

        claimed = InstagramFeedScheduler().claim_run(db, schedule, svc, ctx)

        assert claimed is not None
        snapshot = db.query(TaskScheduleRun).filter_by(id=claimed.run.id).one().get_config_snapshot()
        assert snapshot["scheduled_for"] == datetime(2026, 5, 4, 22, 0).isoformat()
        assert snapshot["schedule_params"]["time_windows"] == [
            {"start": value, "end": value} for value in OPERATIONAL_EXACT_SLOTS
        ]
    finally:
        db.close()


def test_claim_run_T_does_not_create_run_after_tolerance():
    db = _sqlite_session()
    try:
        schedule = TaskSchedule(
            name="instagram_feed_account_6",
            target_type=TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            enabled=True,
            schedule_value=json.dumps(
                {
                    "daily_runs": 8,
                    "time_windows": [{"start": value, "end": value} for value in OPERATIONAL_EXACT_SLOTS],
                }
            ),
        )
        schedule.set_target_config({"service_account_id": 6, "min_interval_hours": 2})
        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        claimed = InstagramFeedScheduler().claim_run(
            db,
            schedule,
            TaskScheduleService(db),
            WorkerContext(
                worker_name="scheduled_worker",
                browser_manager=None,
                db_factory=MagicMock(),
                now=datetime(2026, 5, 4, 22, 9),
            ),
        )

        assert claimed is None
        assert db.query(TaskScheduleRun).count() == 0
    finally:
        db.close()


def test_claim_run_T_active_run_blocks_duplicate_claim():
    db = _sqlite_session()
    try:
        schedule = TaskSchedule(
            name="instagram_feed_account_6",
            target_type=TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            enabled=True,
            schedule_value=json.dumps(
                {
                    "daily_runs": 8,
                    "time_windows": [{"start": value, "end": value} for value in OPERATIONAL_EXACT_SLOTS],
                }
            ),
        )
        schedule.set_target_config({"service_account_id": 6, "min_interval_hours": 2})
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        TaskScheduleService(db).start_run(schedule.id, worker_id="scheduled_worker")

        claimed = InstagramFeedScheduler().claim_run(
            db,
            schedule,
            TaskScheduleService(db),
            WorkerContext(
                worker_name="scheduled_worker",
                browser_manager=None,
                db_factory=MagicMock(),
                now=datetime(2026, 5, 4, 22, 4),
            ),
        )

        assert claimed is None
        assert db.query(TaskScheduleRun).count() == 1
    finally:
        db.close()


@pytest.mark.asyncio
async def test_execute_requires_execute_with_tab_context():
    scheduler = InstagramFeedScheduler()
    schedule = MagicMock(id=1)
    schedule.get_target_config.return_value = {"service_account_id": 7}
    ctx = WorkerContext(worker_name="test_worker", browser_manager=None, db_factory=MagicMock())

    with pytest.raises(RuntimeError, match="execute_with_tab"):
        await scheduler.execute(
            schedule,
            ClaimedRun(run=MagicMock(id=2), task_name="instagram_schedule_1_run_2"),
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
