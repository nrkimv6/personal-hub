"""E2E coverage for nightly repo sync scheduled-worker dispatch."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import MagicMock, patch

from app.models.base import Base
from app.models.plan_record import PlanRecord  # noqa: F401 - registers FK target table
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.models.tracking_item import TrackingItem  # noqa: F401 - registers scheduler blocker table
from app.modules.claude_worker.models.llm_request import LLMRequest  # noqa: F401 - registers report FK target
from app.modules.reports.models.generated_report import GeneratedReport


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "checkout", "-b", "main")
    _run_git(repo, "config", "user.email", "nightly@example.test")
    _run_git(repo, "config", "user.name", "Nightly Test")
    (repo / "README.md").write_text("# temp repo\n", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-m", "init")


async def _drain_running_tasks(worker) -> None:
    if worker._running_tasks:
        await asyncio.gather(*list(worker._running_tasks))
        worker._cleanup_completed_tasks()


def _build_worker(session_factory):
    from app.worker.scheduled_worker import ScheduledCrawlWorker

    with patch("app.worker.scheduled_worker.SessionLocal", session_factory):
        worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    worker._worker_ctx.db_factory = session_factory
    worker._worker_ctx.update_worker_state = None
    return worker


@pytest.mark.asyncio
async def test_nightly_repo_sync_schedule_dispatch_saves_report(session_factory, tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    with session_factory() as db:
        schedule = TaskSchedule(
            name="nightly_repo_sync_daily",
            display_name="Nightly Repo Sync",
            target_type=TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC,
            schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
            schedule_value="0 3 * * *",
            enabled=True,
        )
        schedule.set_target_config({"repo_root": str(repo), "allow_mutation": False})
        db.add(schedule)
        db.commit()

    worker = _build_worker(session_factory)

    with patch(
        "app.modules.dev_runner.schedulers.nightly_repo_sync_schedule.should_run_cron",
        return_value=True,
    ), patch("app.worker.scheduled_worker.SessionLocal", session_factory):
        await worker._main_loop_iteration()
        await _drain_running_tasks(worker)

    with session_factory() as db:
        run = db.query(TaskScheduleRun).one()
        report = db.query(GeneratedReport).one()

    assert run.status == TaskScheduleRun.STATUS_COMPLETED
    assert run.stop_reason == "completed"
    assert report.report_type == "nightly_repo_sync"
    assert report.schedule_run_id == run.id
    assert str(repo) in report.content
