"""Nightly repo sync scheduler contracts."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.models.task_schedule import TaskSchedule
from app.modules.dev_runner.schedulers.nightly_repo_sync_schedule import NightlyRepoSyncScheduler
from app.modules.dev_runner.services.nightly_repo_sync_service import (
    BranchSyncState,
    RepoSyncSnapshot,
    TrackingReportDecision,
)
from app.worker.schedule_handler_base import ClaimedRun, ScheduleExecutionSpec, WorkerContext


def _schedule() -> TaskSchedule:
    schedule = TaskSchedule(
        id=10,
        name="nightly_repo_sync_daily",
        target_type=TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
        schedule_value="0 3 * * *",
        enabled=True,
    )
    schedule.set_target_config({"repo_root": "D:/repo", "allow_mutation": False})
    return schedule


def test_claim_run_R_cron_due_creates_claimed_run() -> None:
    scheduler = NightlyRepoSyncScheduler()
    svc = MagicMock()
    svc.get_latest_run.return_value = SimpleNamespace(started_at=datetime.now() - timedelta(days=1))
    svc.has_active_run.return_value = False
    svc.start_run.return_value = SimpleNamespace(id=99)
    ctx = WorkerContext(worker_name="test-worker", browser_manager=None, db_factory=MagicMock())

    with patch("app.modules.dev_runner.schedulers.nightly_repo_sync_schedule.should_run_cron", return_value=True):
        claimed = scheduler.claim_run(MagicMock(), _schedule(), svc, ctx)

    assert claimed is not None
    assert claimed.run_id == 99
    assert claimed.task_name.startswith("nightly_repo_sync_")


@pytest.mark.asyncio
async def test_execute_R_saves_generated_report() -> None:
    scheduler = NightlyRepoSyncScheduler()
    db = MagicMock()
    db_factory = MagicMock(return_value=db)
    db.__enter__.return_value = db
    ctx = WorkerContext(worker_name="test-worker", browser_manager=None, db_factory=db_factory)
    spec = ScheduleExecutionSpec(
        schedule_id=10,
        target_type=TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC,
        name="nightly_repo_sync_daily",
        target_config={"repo_root": "D:/repo", "allow_mutation": False},
        schedule_value="0 3 * * *",
        schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
        display_name="Nightly Repo Sync",
    )
    claimed = ClaimedRun(run_id=55, schedule_id=10, task_name="nightly_repo_sync_55", config_snapshot_patch={})

    with patch("app.modules.dev_runner.schedulers.nightly_repo_sync_schedule.NightlyRepoSyncService") as svc_cls:
        svc_cls.return_value.run.return_value = RepoSyncSnapshot(
            repo_root="D:/repo",
            collected_at="2026-05-07T03:00:00",
            root=BranchSyncState(name="main"),
            tracking=TrackingReportDecision(status="completed", title="ok", description="ok"),
        )
        outcome = await scheduler.execute(spec, claimed, ctx)

    assert outcome.saved_count == 1
    assert outcome.stop_reason in {"completed", "report_only"}
    assert db.add.called
    assert db.commit.called


@pytest.mark.asyncio
async def test_execute_E_blocked_stage_upserts_tracking_item() -> None:
    scheduler = NightlyRepoSyncScheduler()
    db = MagicMock()
    db_factory = MagicMock(return_value=db)
    db.__enter__.return_value = db
    db.query.return_value.filter.return_value.first.return_value = None
    ctx = WorkerContext(worker_name="test-worker", browser_manager=None, db_factory=db_factory)
    spec = ScheduleExecutionSpec(
        schedule_id=10,
        target_type=TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC,
        name="nightly_repo_sync_daily",
        target_config={"repo_root": "D:/repo", "allow_mutation": True},
        schedule_value="0 3 * * *",
        schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
        display_name="Nightly Repo Sync",
    )
    claimed = ClaimedRun(run_id=55, schedule_id=10, task_name="nightly_repo_sync_55", config_snapshot_patch={})

    with patch("app.modules.dev_runner.schedulers.nightly_repo_sync_schedule.NightlyRepoSyncService") as svc_cls:
        snapshot = RepoSyncSnapshot(
            repo_root="D:/repo",
            collected_at="2026-05-07T03:00:00",
            actions=[],
            root=BranchSyncState(name="main", dirty=True),
            tracking=TrackingReportDecision(status="blocked", title="blocked", description="desc", block_reason="root_dirty"),
        )
        svc_cls.return_value.run.return_value = snapshot
        outcome = await scheduler.execute(spec, claimed, ctx)

    assert outcome.stop_reason == "blocked"
    assert db.add.called
    assert db.commit.called


@pytest.mark.asyncio
async def test_execute_B_duplicate_block_dedupes_tracking_item() -> None:
    scheduler = NightlyRepoSyncScheduler()
    existing = SimpleNamespace(description="", updated_at=None)
    db = MagicMock()
    db_factory = MagicMock(return_value=db)
    db.__enter__.return_value = db
    db.query.return_value.filter.return_value.first.return_value = existing
    ctx = WorkerContext(worker_name="test-worker", browser_manager=None, db_factory=db_factory)
    spec = ScheduleExecutionSpec(
        schedule_id=10,
        target_type=TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC,
        name="nightly_repo_sync_daily",
        target_config={"repo_root": "D:/repo", "allow_mutation": True},
        schedule_value="0 3 * * *",
        schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
        display_name="Nightly Repo Sync",
    )
    claimed = ClaimedRun(run_id=55, schedule_id=10, task_name="nightly_repo_sync_55", config_snapshot_patch={})

    with patch("app.modules.dev_runner.schedulers.nightly_repo_sync_schedule.NightlyRepoSyncService") as svc_cls:
        snapshot = RepoSyncSnapshot(
            repo_root="D:/repo",
            collected_at="2026-05-07T03:00:00",
            actions=[],
            root=BranchSyncState(name="main", dirty=True),
            tracking=TrackingReportDecision(status="blocked", title="blocked", description="desc", block_reason="root_dirty"),
        )
        svc_cls.return_value.run.return_value = snapshot
        outcome = await scheduler.execute(spec, claimed, ctx)

    assert outcome.stop_reason == "blocked"
    assert "nightly_repo_sync:block:root_dirty" in existing.description
    assert existing.updated_at is not None
