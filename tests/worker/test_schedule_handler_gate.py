"""Shared worker lifecycle tests for schedule handlers."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.modules.writing.schedulers.keyword_analysis_schedule import KeywordAnalysisScheduler
from app.modules.writing.schedulers.writing_source_schedule import WritingSourceScheduler
from app.modules.writing.schedulers.writing_task_schedule import WritingTaskScheduler
from app.worker.schedule_handler_base import ClaimedRun, HandlerRunOutcome, WorkerContext
from app.worker.scheduled_worker import ScheduledCrawlWorker


def _make_ctx():
    return WorkerContext(
        worker_name="scheduled_worker",
        browser_manager=None,
        db_factory=MagicMock(),
        update_worker_state=MagicMock(),
    )


def test_claim_run_starts_run_when_time_window_is_due():
    handler = WritingTaskScheduler()
    db = MagicMock()
    schedule = MagicMock(id=7)
    schedule.get_target_config.return_value = {
        "daily_runs": 1,
        "time_windows": [{"start": "09:00", "end": "18:00"}],
        "min_interval_hours": 1,
    }
    svc = MagicMock()
    svc.get_latest_run.return_value = None
    svc.has_active_run.return_value = False
    svc.start_run.return_value = MagicMock(id=11)

    fake_scheduler = MagicMock()
    fake_scheduler.should_run_now.return_value = True

    with patch(
        "app.modules.writing.schedulers.writing_task_schedule.build_time_window_scheduler",
        return_value=fake_scheduler,
    ):
        claimed = handler.claim_run(db, schedule, svc, _make_ctx())

    assert claimed is not None
    assert claimed.task_name == "writing_schedule_7_run_11"
    svc.start_run.assert_called_once_with(
        schedule_id=7,
        worker_id="scheduled_worker",
        config_snapshot=schedule.get_target_config.return_value,
    )


def test_claim_run_prefers_pending_manual_run_over_due_check():
    handler = WritingSourceScheduler()
    db = MagicMock()
    schedule = MagicMock(id=9)
    schedule.get_target_config.return_value = {
        "daily_runs": 1,
        "time_windows": [{"start": "09:00", "end": "18:00"}],
    }
    manual_run = MagicMock(id=21, worker_id="manual")
    svc = MagicMock()
    svc.get_pending_manual_run.return_value = manual_run

    claimed = handler.claim_run(db, schedule, svc, _make_ctx())

    assert claimed is not None
    assert claimed.run is manual_run
    assert claimed.task_name == "writing_source_9_run_21"
    assert manual_run.worker_id == "scheduled_worker"
    svc.start_run.assert_not_called()
    db.commit.assert_called_once()


def test_claim_run_returns_none_when_interval_not_due():
    handler = KeywordAnalysisScheduler()
    db = MagicMock()
    schedule = MagicMock(id=13)
    schedule.get_target_config.return_value = {"min_interval_hours": 24}
    svc = MagicMock()
    svc.get_pending_manual_run.return_value = None
    svc.get_latest_run.return_value = MagicMock(started_at=datetime.now())

    claimed = handler.claim_run(db, schedule, svc, _make_ctx())

    assert claimed is None
    svc.start_run.assert_not_called()


@pytest.mark.asyncio
async def test_schedule_claimed_run_skips_when_task_is_already_running():
    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    worker._create_task = MagicMock()
    worker._is_task_running = MagicMock(return_value=True)
    handler = MagicMock(target_type="dummy")
    schedule = MagicMock(id=1)
    claimed = ClaimedRun(run=MagicMock(id=2), task_name="dummy_1_run_2")

    await worker._schedule_claimed_run(handler, schedule, claimed)

    worker._create_task.assert_not_called()


@pytest.mark.asyncio
async def test_run_handler_completes_and_merges_config_snapshot():
    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    handler = MagicMock()
    handler.target_type = "dummy"
    handler.execute.return_value = HandlerRunOutcome(
        collected_count=2,
        saved_count=1,
        stop_reason="completed",
        config_snapshot_patch={"outcome": "patched"},
    )
    schedule = MagicMock(id=7)
    claimed = ClaimedRun(
        run=MagicMock(id=3),
        task_name="dummy_7_run_3",
        config_snapshot_patch={"claimed": "yes"},
    )

    db = MagicMock()
    run_obj = MagicMock()
    run_obj.get_config_snapshot.return_value = {"existing": "keep"}
    db.query.return_value.filter_by.return_value.first.return_value = run_obj
    svc = MagicMock()

    with patch("app.worker.scheduled_worker.SessionLocal", return_value=db), patch(
        "app.worker.scheduled_worker.TaskScheduleService",
        return_value=svc,
    ):
        await worker._run_handler(handler, schedule, claimed)

    svc.complete_run.assert_called_once_with(
        3,
        collected_count=2,
        saved_count=1,
        stop_reason="completed",
    )
    run_obj.set_config_snapshot.assert_called_once_with(
        {"existing": "keep", "claimed": "yes", "outcome": "patched"}
    )
    svc.update_schedule_after_run.assert_called_once_with(7)
    db.close.assert_called_once()


@pytest.mark.asyncio
async def test_run_handler_records_fail_run_when_execute_raises():
    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    worker._log_worker_error = MagicMock()
    handler = MagicMock()
    handler.target_type = "dummy"
    handler.execute.side_effect = RuntimeError("boom")
    schedule = MagicMock(id=7)
    claimed = ClaimedRun(run=MagicMock(id=3), task_name="dummy_7_run_3")

    db = MagicMock()
    svc = MagicMock()

    with patch("app.worker.scheduled_worker.SessionLocal", return_value=db), patch(
        "app.worker.scheduled_worker.TaskScheduleService",
        return_value=svc,
    ):
        await worker._run_handler(handler, schedule, claimed)

    svc.fail_run.assert_called_once_with(3, error_message="boom")
    worker._log_worker_error.assert_called_once()
    db.close.assert_called_once()
