"""Focused ScheduleDateExpireScheduler contract tests."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.worker.schedule_handler_base import ClaimedRun, ScheduleExecutionSpec, WorkerContext
from app.worker.schedulers.schedule_date_expire_schedule import ScheduleDateExpireScheduler


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE monitor_schedules (
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


@pytest.mark.asyncio
async def test_execute_returns_affected_ids_patch(session_factory):
    with session_factory() as db:
        db.execute(
            text(
                """
                INSERT INTO monitor_schedules (date, is_enabled, updated_at)
                VALUES ('2026-04-21', 1, CURRENT_TIMESTAMP), ('2099-12-31', 1, CURRENT_TIMESTAMP)
                """
            )
        )
        db.commit()

    scheduler = ScheduleDateExpireScheduler()
    ctx = WorkerContext(worker_name="test_worker", browser_manager=None, db_factory=session_factory)

    with patch("app.worker.schedulers.schedule_date_expire_schedule.get_today_kst_iso", return_value="2026-04-22"):
        outcome = await scheduler.execute(
            ScheduleExecutionSpec(
                schedule_id=1,
                target_type="schedule_date_expire",
                name="schedule_date_expire",
                target_config={},
                schedule_value=None,
                schedule_type="cron",
                display_name="Schedule Date Expire",
            ),
            ClaimedRun(run_id=2, schedule_id=1, task_name="schedule_date_expire_1_run_2"),
            ctx,
        )

    assert outcome.collected_count == 1
    assert outcome.config_snapshot_patch["affected_count"] == 1
    assert len(outcome.config_snapshot_patch["affected_ids"]) == 1
