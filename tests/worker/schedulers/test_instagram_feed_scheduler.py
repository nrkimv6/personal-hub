"""Focused InstagramFeedScheduler contract tests."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import TaskSchedule
from app.modules.instagram.models.schemas import TimeWindow
from app.modules.instagram.schedulers.feed_schedule import InstagramFeedScheduler
from app.modules.instagram.services.scheduler import InstagramScheduler
from app.worker.schedule_handler_base import ClaimedRun, WorkerContext


def test_operational_exact_slot_schedule_generates_eight_same_day_slots():
    run_date = datetime(2026, 5, 3).date()
    windows = [
        TimeWindow(start=value, end=value)
        for value in ["07:00", "09:20", "11:40", "14:00", "16:20", "18:40", "21:00", "23:20"]
    ]
    scheduler = InstagramScheduler(daily_runs=8, time_windows=windows)

    schedule = scheduler.generate_daily_schedule(run_date)

    assert schedule == [
        datetime(2026, 5, 3, 7, 0),
        datetime(2026, 5, 3, 9, 20),
        datetime(2026, 5, 3, 11, 40),
        datetime(2026, 5, 3, 14, 0),
        datetime(2026, 5, 3, 16, 20),
        datetime(2026, 5, 3, 18, 40),
        datetime(2026, 5, 3, 21, 0),
        datetime(2026, 5, 3, 23, 20),
    ]


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
            lambda self, last_run=None, min_interval_hours=0: due_run_time,
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
async def test_is_logged_in_distinguishes_logged_out_and_logged_in_pages():
    scheduler = InstagramFeedScheduler()

    logged_out_page = MagicMock()
    logged_out_page.query_selector = AsyncMock(side_effect=[object()])
    assert await scheduler._is_logged_in(logged_out_page) is False

    logged_in_page = MagicMock()
    logged_in_page.query_selector = AsyncMock(side_effect=[None, None, None, None, object()])
    assert await scheduler._is_logged_in(logged_in_page) is True
