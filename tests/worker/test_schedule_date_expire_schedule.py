"""Schedule date expire handler tests."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.monitor_schedule_cutoff import get_today_kst_iso
from app.worker.schedule_handler_base import WorkerContext
from app.worker.schedulers.schedule_date_expire_schedule import ScheduleDateExpireScheduler

_KST = timezone(timedelta(hours=9))


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


def _make_ctx(session_factory):
    return WorkerContext(
        worker_name="test_worker",
        browser_manager=None,
        db_factory=session_factory,
    )


class TestScheduleDateExpireClaimRun:
    def test_claim_run_starts_run_when_cron_due(self, session_factory):
        scheduler = ScheduleDateExpireScheduler()
        db = session_factory()
        schedule = MagicMock(id=1)
        svc = MagicMock()
        run = MagicMock(id=10)
        svc.get_latest_run.return_value = None
        svc.has_active_run.return_value = False
        svc.start_run.return_value = run

        with patch(
            "app.worker.schedulers.schedule_date_expire_schedule.should_run_cron",
            return_value=True,
        ):
            claimed = scheduler.claim_run(db, schedule, svc, _make_ctx(session_factory))

        assert claimed is not None
        assert claimed.task_name == "schedule_date_expire_1_run_10"
        svc.start_run.assert_called_once_with(
            schedule_id=1,
            worker_id="test_worker",
            config_snapshot={},
        )
        db.close()

    def test_claim_run_skips_when_active_run_exists(self, session_factory):
        scheduler = ScheduleDateExpireScheduler()
        db = session_factory()
        schedule = MagicMock(id=1)
        svc = MagicMock()
        svc.get_latest_run.return_value = None
        svc.has_active_run.return_value = True

        with patch(
            "app.worker.schedulers.schedule_date_expire_schedule.should_run_cron",
            return_value=True,
        ):
            claimed = scheduler.claim_run(db, schedule, svc, _make_ctx(session_factory))

        assert claimed is None
        svc.start_run.assert_not_called()
        db.close()


class TestScheduleDateExpireExecute:
    @pytest.mark.asyncio
    async def test_execute_disables_only_past_rows(self, session_factory):
        scheduler = ScheduleDateExpireScheduler()
        with session_factory() as db:
            db.execute(
                text(
                    """
                    INSERT INTO monitor_schedules (date, is_enabled, updated_at)
                    VALUES
                    ('2026-04-21', 1, CURRENT_TIMESTAMP),
                    ('2026-04-22', 1, CURRENT_TIMESTAMP),
                    ('2099-12-31', 1, CURRENT_TIMESTAMP)
                    """
                )
            )
            db.commit()

        with patch(
            "app.worker.schedulers.schedule_date_expire_schedule.get_today_kst_iso",
            return_value="2026-04-22",
        ):
            outcome = await scheduler.execute(MagicMock(id=5), MagicMock(), _make_ctx(session_factory))

        assert outcome.collected_count == 1
        assert outcome.saved_count == 1
        assert outcome.stop_reason == "completed"
        assert outcome.config_snapshot_patch["cutoff_date"] == "2026-04-22"
        assert outcome.config_snapshot_patch["affected_count"] == 1

        with session_factory() as db:
            rows = db.execute(
                text("SELECT id, date, is_enabled FROM monitor_schedules ORDER BY id")
            ).fetchall()

        assert rows[0].date == "2026-04-21" and rows[0].is_enabled == 0
        assert rows[1].date == "2026-04-22" and rows[1].is_enabled == 1
        assert rows[2].date == "2099-12-31" and rows[2].is_enabled == 1

    @pytest.mark.asyncio
    async def test_execute_is_idempotent_when_no_past_rows(self, session_factory):
        scheduler = ScheduleDateExpireScheduler()
        with session_factory() as db:
            db.execute(
                text(
                    """
                    INSERT INTO monitor_schedules (date, is_enabled, updated_at)
                    VALUES ('2099-12-31', 1, CURRENT_TIMESTAMP)
                    """
                )
            )
            db.commit()

        with patch(
            "app.worker.schedulers.schedule_date_expire_schedule.get_today_kst_iso",
            return_value="2026-04-22",
        ):
            outcome = await scheduler.execute(MagicMock(id=5), MagicMock(), _make_ctx(session_factory))

        assert outcome.collected_count == 0
        assert outcome.saved_count == 0
        assert outcome.config_snapshot_patch["affected_ids"] == []


class TestGetTodayKstIso:
    def test_midnight_boundary_kst(self):
        before_midnight_kst = datetime(2026, 4, 22, 23, 59, 59, tzinfo=_KST)
        after_midnight_kst = datetime(2026, 4, 23, 0, 0, 1, tzinfo=_KST)

        assert get_today_kst_iso(before_midnight_kst) == "2026-04-22"
        assert get_today_kst_iso(after_midnight_kst) == "2026-04-23"

    def test_utc_time_converts_to_kst(self):
        utc_time = datetime(2026, 4, 22, 15, 0, 0, tzinfo=timezone.utc)
        utc_time2 = datetime(2026, 4, 22, 14, 59, 0, tzinfo=timezone.utc)

        assert get_today_kst_iso(utc_time) == "2026-04-23"
        assert get_today_kst_iso(utc_time2) == "2026-04-22"
