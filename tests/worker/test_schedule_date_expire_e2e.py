"""Schedule date expire registry and dispatch tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.task_schedule import TaskSchedule
from app.worker.schedule_handler_base import ClaimedRun, ScheduleExecutionSpec
from app.worker.scheduled_worker import ScheduledCrawlWorker
from app.worker.schedulers.schedule_date_expire_schedule import ScheduleDateExpireScheduler


def test_schedule_date_expire_handler_is_registered():
    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    assert any(
        isinstance(handler, ScheduleDateExpireScheduler)
        for handler in worker._handlers
    )


@pytest.mark.asyncio
async def test_dispatch_uses_schedule_date_expire_handler_registry():
    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    handler = ScheduleDateExpireScheduler()
    schedule = MagicMock(
        id=1,
        target_type=TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE,
        name="schedule_date_expire",
        schedule_value=None,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
        display_name="Schedule Date Expire",
    )
    schedule.get_target_config.return_value = {}
    claimed = ClaimedRun(run_id=10, schedule_id=1, task_name="schedule_date_expire_1_run_10")
    db = MagicMock()
    svc = MagicMock()
    svc.get_schedules_by_type.side_effect = lambda target_type, enabled_only=True: (
        [schedule] if target_type == TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE else []
    )

    with patch.object(handler, "claim_run", return_value=claimed), patch(
        "app.worker.scheduled_worker.SessionLocal",
        return_value=db,
    ), patch(
        "app.worker.scheduled_worker.TaskScheduleService",
        return_value=svc,
    ):
        worker._handlers = [handler]
        worker._schedule_claimed_run = AsyncMock()
        await worker._dispatch_scheduled_runs()

    worker._schedule_claimed_run.assert_awaited_once()
    called_handler, spec, called_claimed = worker._schedule_claimed_run.await_args.args
    assert called_handler is handler
    assert isinstance(spec, ScheduleExecutionSpec)
    assert spec.schedule_id == 1
    assert called_claimed is claimed
    db.close.assert_called_once()
