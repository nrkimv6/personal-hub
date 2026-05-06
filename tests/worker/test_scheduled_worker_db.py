"""Scheduled worker DB lifecycle tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.scheduled_worker import ScheduledCrawlWorker


class TestDispatchDbSessionLeak:
    @pytest.mark.asyncio
    async def test_dispatch_closes_db_after_success(self):
        worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
        db = MagicMock()
        svc = MagicMock()
        svc.get_schedules_by_type.return_value = []
        handler = MagicMock()
        handler.target_type = "dummy"
        worker._handlers = [handler]

        with patch("app.worker.scheduled_worker.SessionLocal", return_value=db), patch(
            "app.worker.scheduled_worker.TaskScheduleService",
            return_value=svc,
        ):
            await worker._dispatch_scheduled_runs()

        db.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_closes_db_after_claim_exception(self):
        worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
        db = MagicMock()
        svc = MagicMock()
        schedule = MagicMock(id=1)
        svc.get_schedules_by_type.return_value = [schedule]
        handler = MagicMock()
        handler.target_type = "dummy"
        handler.claim_run.side_effect = RuntimeError("boom")
        worker._handlers = [handler]
        worker._log_worker_error = MagicMock()

        with patch("app.worker.scheduled_worker.SessionLocal", return_value=db), patch(
            "app.worker.scheduled_worker.TaskScheduleService",
            return_value=svc,
        ):
            await worker._dispatch_scheduled_runs()

        worker._log_worker_error.assert_called_once()
        db.close.assert_called_once()
