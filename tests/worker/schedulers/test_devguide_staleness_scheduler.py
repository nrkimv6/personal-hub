"""Focused DevguideStalenessScheduler contract tests."""

from unittest.mock import MagicMock, patch

import pytest

from app.modules.dev_runner.schedulers.devguide_staleness_schedule import DevguideStalenessScheduler
from app.worker.schedule_handler_base import ClaimedRun, ScheduleExecutionSpec, WorkerContext


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
            ScheduleExecutionSpec(
                schedule_id=1,
                target_type="devguide_staleness",
                name="devguide",
                target_config={},
                schedule_value=None,
                schedule_type="cron",
                display_name="Devguide",
            ),
            ClaimedRun(run_id=2, schedule_id=1, task_name="devguide_1_run_2"),
            ctx,
        )

    assert outcome.collected_count == 2
    assert outcome.saved_count == 2
    assert outcome.config_snapshot_patch == {"stale_guides": 2}
