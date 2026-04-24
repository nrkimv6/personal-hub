"""Focused DevguideStalenessScheduler contract tests."""

from unittest.mock import MagicMock, patch

import pytest

from app.modules.dev_runner.schedulers.devguide_staleness_schedule import DevguideStalenessScheduler
from app.worker.schedule_handler_base import ClaimedRun, WorkerContext


@pytest.mark.asyncio
async def test_execute_returns_counts_only_outcome_from_stale_report():
    scheduler = DevguideStalenessScheduler()
    ctx = WorkerContext(
        worker_name="test_worker",
        browser_manager=None,
        db_factory=MagicMock(),
    )

    with patch(
        "app.modules.dev_runner.schedulers.devguide_staleness_schedule.build_devguide_staleness_report",
        return_value=[{"path": "docs/a.md"}, {"path": "docs/b.md"}],
    ), patch(
        "app.modules.dev_runner.schedulers.devguide_staleness_schedule.save_devguide_staleness_result",
    ):
        outcome = await scheduler.execute(
            MagicMock(id=1),
            ClaimedRun(run=MagicMock(id=2), task_name="devguide_1_run_2"),
            ctx,
        )

    assert outcome.collected_count == 2
    assert outcome.saved_count == 2
    assert outcome.config_snapshot_patch == {"stale_guides": 2}
