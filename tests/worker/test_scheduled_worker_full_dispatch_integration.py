"""Full dispatch integration tests for the scheduled worker registry."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.modules.claude_worker.models.llm_request import LLMRequest


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS monitor_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    is_enabled BOOLEAN NOT NULL DEFAULT 1,
                    updated_at DATETIME
                )
                """
            )
        )
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()


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


def _create_schedule(
    db,
    *,
    name: str,
    target_type: str,
    target_config: dict | None = None,
    schedule_type: str = TaskSchedule.SCHEDULE_TYPE_CRON,
    schedule_value: str = "0 2 * * *",
):
    schedule = TaskSchedule(
        name=name,
        display_name=name,
        target_type=target_type,
        schedule_type=schedule_type,
        schedule_value=schedule_value,
        enabled=True,
    )
    if target_config:
        schedule.set_target_config(target_config)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@pytest.mark.asyncio
async def test_full_dispatch_registry_contains_all_12_handlers(session_factory):
    worker = _build_worker(session_factory)

    assert len(worker._handlers) == 13
    assert [handler.target_type for handler in worker._handlers] == [
        TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
        TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH,
        TaskSchedule.TARGET_TYPE_WRITING_TASK,
        TaskSchedule.TARGET_TYPE_WRITING_SOURCE_COLLECT,
        TaskSchedule.TARGET_TYPE_KEYWORD_ANALYSIS,
        TaskSchedule.TARGET_TYPE_TOPIC_EXTRACT,
        TaskSchedule.TARGET_TYPE_REPORT,
        TaskSchedule.TARGET_TYPE_PYTEST_RUN,
        TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE,
        TaskSchedule.TARGET_TYPE_DEVGUIDE_STALENESS,
        TaskSchedule.TARGET_TYPE_ARCHIVE_ROTATION,
        TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE,
        TaskSchedule.TARGET_TYPE_AUTO_DEV_RUNNER,
    ]


@pytest.mark.asyncio
async def test_main_loop_iteration_queues_plan_archive_request(session_factory):
    from app.modules.dev_runner.schedulers.plan_archive_schedule import PlanArchiveScheduler

    with session_factory() as db:
        _create_schedule(
            db,
            name="plan-archive-full-dispatch",
            target_type=TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE,
        )
        db.add(
            PlanRecord(
                filename_hash="plan-archive-hash",
                file_path="/archive/2026-04-24_plan.md",
                raw_content="# archive\nworker dispatch integration",
                archived_at=datetime(2026, 4, 24),
                llm_processed_at=None,
            )
        )
        db.commit()

    worker = _build_worker(session_factory)
    worker._handlers = [PlanArchiveScheduler()]

    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch(
        "app.modules.dev_runner.schedulers.plan_archive_schedule.should_run_cron",
        return_value=True,
    ), patch(
        "app.modules.dev_runner.schedulers.plan_archive_schedule.LLMService",
        return_value=fake_llm,
    ), patch(
        "app.modules.dev_runner.schedulers.plan_archive_schedule.build_plan_analyze_prompt",
        side_effect=lambda file_content, filename: f"{filename}::{file_content}",
    ), patch("app.worker.scheduled_worker.SessionLocal", session_factory):
        await worker._main_loop_iteration()
        await _drain_running_tasks(worker)

    with session_factory() as db:
        run = db.query(TaskScheduleRun).one()
        request = db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").one()

    assert run.status == TaskScheduleRun.STATUS_COMPLETED
    assert run.collected_count == 1
    assert run.saved_count == 1
    assert request.caller_id == "plan-archive-hash"
    assert "worker dispatch integration" in request.prompt


@pytest.mark.asyncio
async def test_main_loop_iteration_consumes_manual_run_without_duplicate_start(session_factory):
    from app.modules.writing.schedulers.writing_source_schedule import WritingSourceScheduler
    from app.worker.schedule_handler_base import HandlerRunOutcome

    with session_factory() as db:
        schedule = _create_schedule(
            db,
            name="writing-source-manual",
            target_type=TaskSchedule.TARGET_TYPE_WRITING_SOURCE_COLLECT,
            target_config={"collect_rss": False, "collect_wikisource": False},
            schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            schedule_value=json.dumps({"time_windows": [{"start": "09:00", "end": "18:00"}]}),
        )
        manual_run = TaskScheduleRun(
            schedule_id=schedule.id,
            status=TaskScheduleRun.STATUS_RUNNING,
            worker_id="manual",
        )
        db.add(manual_run)
        db.commit()
        db.refresh(manual_run)
        manual_run_id = manual_run.id

    worker = _build_worker(session_factory)
    handler = WritingSourceScheduler()
    worker._handlers = [handler]

    with patch.object(
        WritingSourceScheduler,
        "execute",
        AsyncMock(return_value=HandlerRunOutcome(collected_count=0, saved_count=0)),
    ), patch("app.worker.scheduled_worker.SessionLocal", session_factory):
        await worker._main_loop_iteration()
        await _drain_running_tasks(worker)

    with session_factory() as db:
        runs = db.query(TaskScheduleRun).order_by(TaskScheduleRun.id.asc()).all()

    assert len(runs) == 1
    assert runs[0].id == manual_run_id
    assert runs[0].worker_id == "scheduled_worker"
    assert runs[0].status == TaskScheduleRun.STATUS_COMPLETED


@pytest.mark.asyncio
async def test_main_loop_iteration_records_instagram_exact_slot_scheduled_for(session_factory):
    from app.modules.instagram.schedulers.feed_schedule import InstagramFeedScheduler
    from app.worker.schedule_handler_base import HandlerRunOutcome

    now = datetime.now().replace(second=0, microsecond=0)
    slot = now.strftime("%H:%M")
    with session_factory() as db:
        _create_schedule(
            db,
            name="instagram-feed-exact-slot",
            target_type=TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            target_config={"service_account_id": 1, "min_interval_hours": 0},
            schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            schedule_value=json.dumps(
                {
                    "daily_runs": 1,
                    "time_windows": [{"start": slot, "end": slot}],
                }
            ),
        )

    worker = _build_worker(session_factory)
    worker._handlers = [InstagramFeedScheduler()]

    with patch.object(
        InstagramFeedScheduler,
        "execute",
        AsyncMock(return_value=HandlerRunOutcome(collected_count=0, saved_count=0)),
    ), patch("app.worker.scheduled_worker.SessionLocal", session_factory):
        await worker._main_loop_iteration()
        await _drain_running_tasks(worker)

    with session_factory() as db:
        run = db.query(TaskScheduleRun).one()

    assert run.status == TaskScheduleRun.STATUS_COMPLETED
    assert run.get_config_snapshot()["scheduled_for"] == now.isoformat()


@pytest.mark.asyncio
async def test_main_loop_iteration_records_instagram_overnight_rollover_slot(session_factory):
    from app.modules.instagram.schedulers.feed_schedule import InstagramFeedScheduler
    from app.modules.instagram.services.scheduler import InstagramScheduler
    from app.worker.schedule_handler_base import HandlerRunOutcome

    due_run_time = datetime(2026, 5, 4, 0, 1)
    with session_factory() as db:
        _create_schedule(
            db,
            name="instagram-feed-overnight-slot",
            target_type=TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            target_config={"service_account_id": 1, "min_interval_hours": 0},
            schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            schedule_value=json.dumps(
                {
                    "daily_runs": 1,
                    "time_windows": [{"start": "23:59", "end": "00:01"}],
                }
            ),
        )

    worker = _build_worker(session_factory)
    worker._handlers = [InstagramFeedScheduler()]

    with patch.object(
        InstagramScheduler,
        "get_due_run_time",
        return_value=due_run_time,
    ), patch.object(
        InstagramFeedScheduler,
        "execute",
        AsyncMock(return_value=HandlerRunOutcome(collected_count=0, saved_count=0)),
    ), patch("app.worker.scheduled_worker.SessionLocal", session_factory):
        await worker._main_loop_iteration()
        await _drain_running_tasks(worker)

    with session_factory() as db:
        run = db.query(TaskScheduleRun).one()

    assert run.status == TaskScheduleRun.STATUS_COMPLETED
    assert run.get_config_snapshot()["scheduled_for"] == due_run_time.isoformat()


@pytest.mark.asyncio
async def test_main_loop_iteration_uses_counts_only_complete_run_for_system_handler(session_factory):
    from app.modules.dev_runner.schedulers.plan_archive_schedule import PlanArchiveScheduler
    from app.services.task_schedule_service import TaskScheduleService

    captured_kwargs = []
    original_complete_run = TaskScheduleService.complete_run

    def _spy_complete_run(self, run_id, collected_count, saved_count, stop_reason=None, **kwargs):
        captured_kwargs.append(kwargs)
        return original_complete_run(self, run_id, collected_count, saved_count, stop_reason)

    with session_factory() as db:
        _create_schedule(
            db,
            name="schedule-date-expire-contract",
            target_type=TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE,
        )
        db.add(
            PlanRecord(
                filename_hash="counts-only-hash",
                file_path="/archive/2026-04-24_counts-only.md",
                raw_content="# counts only\ncontract",
                archived_at=datetime.now() - timedelta(days=1),
                llm_processed_at=None,
            )
        )
        db.commit()

    worker = _build_worker(session_factory)
    worker._handlers = [PlanArchiveScheduler()]

    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch(
        "app.modules.dev_runner.schedulers.plan_archive_schedule.should_run_cron",
        return_value=True,
    ), patch(
        "app.modules.dev_runner.schedulers.plan_archive_schedule.LLMService",
        return_value=fake_llm,
    ), patch(
        "app.modules.dev_runner.schedulers.plan_archive_schedule.build_plan_analyze_prompt",
        return_value="counts-only",
    ), patch.object(TaskScheduleService, "complete_run", _spy_complete_run), patch(
        "app.worker.scheduled_worker.SessionLocal",
        session_factory,
    ):
        await worker._main_loop_iteration()
        await _drain_running_tasks(worker)

    assert captured_kwargs == [{}]
