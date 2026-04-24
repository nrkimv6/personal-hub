"""Focused InstagramFeedScheduler contract tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.instagram.schedulers.feed_schedule import InstagramFeedScheduler
from app.worker.schedule_handler_base import ClaimedRun, WorkerContext


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
