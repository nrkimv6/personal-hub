from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.plan_record import PlanRecord
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.models.tracking_item import TrackingItem, TrackingItemPlanLink
from app.modules.dev_runner.schedulers.worktree_hygiene_schedule import WorktreeHygieneScheduler
from app.modules.reports.models.generated_report import GeneratedReport
from app.worker.schedule_handler_base import ClaimedRun, WorkerContext, build_schedule_execution_spec


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
    TaskSchedule.__table__.create(bind=engine, checkfirst=True)
    TaskScheduleRun.__table__.create(bind=engine, checkfirst=True)
    GeneratedReport.__table__.create(bind=engine, checkfirst=True)
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    TrackingItem.__table__.create(bind=engine, checkfirst=True)
    TrackingItemPlanLink.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()


def _make_ctx(session_factory):
    return WorkerContext(
        worker_name="test_worker",
        browser_manager=None,
        db_factory=session_factory,
    )


def _schedule(repo: Path) -> TaskSchedule:
    schedule = TaskSchedule(
        id=1,
        name="worktree_hygiene_daily",
        target_type=TaskSchedule.TARGET_TYPE_WORKTREE_HYGIENE,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
        schedule_value="0 8 * * *",
    )
    schedule.set_target_config(
        {
            "repo_root": str(repo),
            "residue_retention_days": 14,
            "auto_delete_residue": False,
            "report_only": True,
        }
    )
    return schedule


def test_claim_run_R_cron_due_creates_claimed_run(session_factory, tmp_path: Path):
    scheduler = WorktreeHygieneScheduler()
    db = session_factory()
    schedule = _schedule(_init_repo(tmp_path))
    svc = MagicMock()
    run = MagicMock(id=10)
    svc.get_latest_run.return_value = None
    svc.has_active_run.return_value = False
    svc.start_run.return_value = run

    with patch("app.modules.dev_runner.schedulers.worktree_hygiene_schedule.should_run_cron", return_value=True):
        claimed = scheduler.claim_run(db, schedule, svc, _make_ctx(session_factory))

    assert claimed is not None
    assert claimed.task_name == "worktree_hygiene_1_run_10"
    svc.start_run.assert_called_once()
    db.close()


def test_claim_run_B_active_run_skips(session_factory, tmp_path: Path):
    scheduler = WorktreeHygieneScheduler()
    db = session_factory()
    schedule = _schedule(_init_repo(tmp_path))
    svc = MagicMock()
    svc.get_latest_run.return_value = None
    svc.has_active_run.return_value = True

    with patch("app.modules.dev_runner.schedulers.worktree_hygiene_schedule.should_run_cron", return_value=True):
        claimed = scheduler.claim_run(db, schedule, svc, _make_ctx(session_factory))

    assert claimed is None
    svc.start_run.assert_not_called()
    db.close()


@pytest.mark.asyncio
async def test_execute_R_saves_generated_report_and_run_summary(session_factory, tmp_path: Path):
    repo = _init_repo(tmp_path)
    scheduler = WorktreeHygieneScheduler()
    schedule = _schedule(repo)
    claimed = ClaimedRun(run_id=20, schedule_id=1, task_name="worktree_hygiene_1_run_20")

    outcome = await scheduler.execute(build_schedule_execution_spec(schedule), claimed, _make_ctx(session_factory))

    assert outcome.saved_count == 1
    assert outcome.stop_reason == "report_only"
    assert outcome.config_snapshot_patch["statistics"]["registered_count"] >= 1
    with session_factory() as db:
        report = db.query(GeneratedReport).filter_by(report_type="worktree_hygiene").one()
        assert report.schedule_run_id == 20
        assert "Worktree Hygiene Report" in report.content


@pytest.mark.asyncio
async def test_execute_R_summary_includes_interest_and_plans_push_counts(session_factory, tmp_path: Path):
    repo = _init_repo(tmp_path)
    residue = repo / ".worktrees" / "post-remove" / ".pytest_cache"
    residue.mkdir(parents=True)
    (residue / "README.md").write_text("cache\n", encoding="utf-8")
    scheduler = WorktreeHygieneScheduler()
    schedule = _schedule(repo)
    claimed = ClaimedRun(run_id=21, schedule_id=1, task_name="worktree_hygiene_1_run_21")

    outcome = await scheduler.execute(build_schedule_execution_spec(schedule), claimed, _make_ctx(session_factory))

    stats = outcome.config_snapshot_patch["statistics"]
    assert "plans_push_needed" in stats
    assert stats["cache_only_residue_count"] == 1


@pytest.mark.asyncio
async def test_execute_R_archive_merge_gap_creates_tracking_item_with_memo(session_factory, tmp_path: Path):
    repo = _init_repo(tmp_path)
    worktree = repo / ".worktrees" / "archive-gap"
    _git(repo, "worktree", "add", str(worktree), "-b", "impl/archive-gap")
    (worktree / "change.txt").write_text("change\n", encoding="utf-8")
    _git(worktree, "add", "change.txt")
    _git(worktree, "commit", "-m", "change")
    archive_dir = repo / ".worktrees" / "plans" / "docs" / "archive"
    archive_dir.mkdir(parents=True)
    plan_path = archive_dir / "archive-gap.md"
    plan_path.write_text(
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

    scheduler = WorktreeHygieneScheduler()
    schedule = _schedule(repo)
    claimed = ClaimedRun(run_id=22, schedule_id=1, task_name="worktree_hygiene_1_run_22")
    await scheduler.execute(build_schedule_execution_spec(schedule), claimed, _make_ctx(session_factory))

    with session_factory() as db:
        item = db.query(TrackingItem).one()
        assert "archive 구현완료 plan" in item.title
        assert "user_confirmation_required=true" in item.description
        assert db.query(TrackingItemPlanLink).count() == 1


@pytest.mark.asyncio
async def test_execute_B_archive_merge_gap_dedupes_existing_tracking_item(session_factory, tmp_path: Path):
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
    scheduler = WorktreeHygieneScheduler()
    schedule = _schedule(repo)
    claimed = ClaimedRun(run_id=23, schedule_id=1, task_name="worktree_hygiene_1_run_23")
    spec = build_schedule_execution_spec(schedule)
    await scheduler.execute(spec, claimed, _make_ctx(session_factory))
    await scheduler.execute(spec, claimed, _make_ctx(session_factory))

    with session_factory() as db:
        assert db.query(TrackingItem).count() == 1


@pytest.mark.asyncio
async def test_execute_B_discarded_archive_never_becomes_merge_candidate(session_factory, tmp_path: Path):
    repo = _init_repo(tmp_path)
    worktree = repo / ".worktrees" / "discarded"
    _git(repo, "worktree", "add", str(worktree), "-b", "impl/discarded")
    (worktree / "change.txt").write_text("change\n", encoding="utf-8")
    _git(worktree, "add", "change.txt")
    _git(worktree, "commit", "-m", "change")
    archive_dir = repo / ".worktrees" / "plans" / "docs" / "archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "discarded.md").write_text(
        "# discarded\n> 상태: 폐기\n> branch: impl/discarded\n> worktree: .worktrees/discarded\n",
        encoding="utf-8",
    )

    scheduler = WorktreeHygieneScheduler()
    schedule = _schedule(repo)
    claimed = ClaimedRun(run_id=24, schedule_id=1, task_name="worktree_hygiene_1_run_24")
    await scheduler.execute(build_schedule_execution_spec(schedule), claimed, _make_ctx(session_factory))

    with session_factory() as db:
        assert db.query(TrackingItem).count() == 0
