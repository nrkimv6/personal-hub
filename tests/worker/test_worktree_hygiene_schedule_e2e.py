from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.plan_record import PlanRecord
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.models.tracking_item import TrackingItem, TrackingItemPlanLink
from app.modules.dev_runner.schedulers.worktree_hygiene_schedule import WorktreeHygieneScheduler
from app.modules.reports.models.generated_report import GeneratedReport
from app.worker.schedule_handler_base import ClaimedRun, WorkerContext


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(repo),
    ).stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    _git(repo, "branch", "-M", "main")
    plans = repo / ".worktrees" / "plans"
    _git(repo, "worktree", "add", str(plans), "-b", "plans")
    return repo


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        TaskSchedule.__table__,
        TaskScheduleRun.__table__,
        GeneratedReport.__table__,
        PlanRecord.__table__,
        TrackingItem.__table__,
        TrackingItemPlanLink.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()


def _ctx(session_factory):
    return WorkerContext(worker_name="e2e_worker", browser_manager=None, db_factory=session_factory)


def _seed_schedule(session_factory, repo: Path) -> tuple[TaskSchedule, TaskScheduleRun]:
    with session_factory() as db:
        schedule = TaskSchedule(
            name="worktree_hygiene_daily",
            target_type=TaskSchedule.TARGET_TYPE_WORKTREE_HYGIENE,
            schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
            schedule_value="0 8 * * *",
        )
        schedule.set_target_config(
            {
                "repo_root": str(repo),
                "auto_delete_residue": False,
                "report_only": True,
                "residue_retention_days": 14,
            }
        )
        db.add(schedule)
        db.flush()
        run = TaskScheduleRun(schedule_id=schedule.id, worker_id="e2e_worker")
        db.add(run)
        db.commit()
        db.refresh(schedule)
        db.refresh(run)
        return schedule, run


@pytest.mark.asyncio
async def test_schedule_execute_creates_report_and_run_snapshot_counts(session_factory, tmp_path: Path):
    repo = _init_repo(tmp_path)
    (repo / ".worktrees" / "empty-residue").mkdir(parents=True)
    schedule, run = _seed_schedule(session_factory, repo)

    outcome = await WorktreeHygieneScheduler().execute(
        schedule,
        ClaimedRun(run=run, task_name="worktree_hygiene_1_run_1"),
        _ctx(session_factory),
    )

    assert outcome.config_snapshot_patch["statistics"]["residue_count"] == 1
    with session_factory() as db:
        report = db.query(GeneratedReport).filter_by(report_type="worktree_hygiene").one()
        assert report.schedule_run_id == run.id
        assert "registered_count" in report.statistics


@pytest.mark.asyncio
async def test_archive_merge_gap_links_tracking_item_to_plan_record(session_factory, tmp_path: Path):
    repo = _init_repo(tmp_path)
    worktree = repo / ".worktrees" / "archive-gap"
    _git(repo, "worktree", "add", str(worktree), "-b", "impl/archive-gap")
    (worktree / "change.txt").write_text("change\n", encoding="utf-8")
    _git(worktree, "add", "change.txt")
    _git(worktree, "commit", "-m", "change")
    archive_dir = repo / ".worktrees" / "plans" / "docs" / "archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "archive-gap.md").write_text(
        "# archive gap\n> 상태: 구현완료\n> branch: impl/archive-gap\n> worktree: .worktrees/archive-gap\n",
        encoding="utf-8",
    )
    with session_factory() as db:
        db.add(
            PlanRecord(
                filename_hash="hash-gap",
                file_path=".worktrees/plans/docs/archive/archive-gap.md",
                title="archive gap",
                status="구현완료",
            )
        )
        db.commit()
    schedule, run = _seed_schedule(session_factory, repo)

    await WorktreeHygieneScheduler().execute(
        schedule,
        ClaimedRun(run=run, task_name="worktree_hygiene_1_run_1"),
        _ctx(session_factory),
    )

    with session_factory() as db:
        item = db.query(TrackingItem).one()
        assert "risk_type" in item.description
        assert "recommended_next_action" in item.description
        assert db.query(TrackingItemPlanLink).count() == 1
