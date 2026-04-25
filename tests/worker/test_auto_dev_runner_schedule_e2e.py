"""auto_dev_runner 스케줄러 worker registry/dispatch/manual-run claim 테스트."""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.modules.dev_runner.schedulers.auto_dev_runner_schedule import AutoDevRunnerScheduler
from app.worker.schedule_handler_base import WorkerContext


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


@pytest.fixture
def session(session_factory):
    with session_factory() as s:
        yield s


def _make_schedule(session) -> TaskSchedule:
    sched = TaskSchedule(
        name="auto_dev_runner_nightly",
        target_type=TaskSchedule.TARGET_TYPE_AUTO_DEV_RUNNER,
        schedule_type="cron",
        schedule_value='{"time": "02:00"}',
        enabled=True,
    )
    session.add(sched)
    session.commit()
    session.refresh(sched)
    return sched


def _make_ctx(session):
    return WorkerContext(
        worker_name="test-worker",
        browser_manager=None,
        db_factory=lambda: session,
    )


# ── registry ──────────────────────────────────────────────────────────────────

def test_auto_dev_runner_in_worker_handlers():
    """AutoDevRunnerScheduler가 ScheduledCrawlWorker._build_handlers() 목록에 포함됨"""
    from app.worker.scheduled_worker import ScheduledCrawlWorker
    with patch("app.worker.scheduled_worker.SessionLocal", MagicMock()):
        worker = ScheduledCrawlWorker.__new__(ScheduledCrawlWorker)
        handlers = worker._build_handlers()
    types = [type(h) for h in handlers]
    assert AutoDevRunnerScheduler in types


# ── claim_run / cron ──────────────────────────────────────────────────────────

def test_claim_run_returns_none_when_not_due(session):
    """cron 시각이 아니면 claim_run → None"""
    sched = _make_schedule(session)
    svc = MagicMock()
    svc.get_latest_run.return_value = None
    svc.has_active_run.return_value = False
    ctx = _make_ctx(session)

    _MODULE = "app.modules.dev_runner.schedulers.auto_dev_runner_schedule"
    with patch(f"{_MODULE}.should_run_cron", return_value=False), \
         patch(f"{_MODULE}.claim_pending_manual_run", return_value=None):
        handler = AutoDevRunnerScheduler()
        result = handler.claim_run(session, sched, svc, ctx)

    assert result is None


def test_claim_run_returns_claimed_when_due(session):
    """cron 시각이면 claim_run → ClaimedRun 반환"""
    sched = _make_schedule(session)
    svc = MagicMock()
    svc.get_latest_run.return_value = None
    svc.has_active_run.return_value = False
    fake_claimed = MagicMock()
    ctx = _make_ctx(session)

    _MODULE = "app.modules.dev_runner.schedulers.auto_dev_runner_schedule"
    with patch(f"{_MODULE}.should_run_cron", return_value=True), \
         patch(f"{_MODULE}.claim_pending_manual_run", return_value=None), \
         patch(f"{_MODULE}.start_claimed_run", return_value=fake_claimed):
        handler = AutoDevRunnerScheduler()
        result = handler.claim_run(session, sched, svc, ctx)

    assert result is not None


# ── manual run claim ──────────────────────────────────────────────────────────

def test_claim_run_consumes_manual_run_first(session):
    """수동 실행 요청이 있으면 cron 이전에 소비"""
    sched = _make_schedule(session)
    svc = MagicMock()
    manual_claimed = MagicMock()
    ctx = _make_ctx(session)

    _MODULE = "app.modules.dev_runner.schedulers.auto_dev_runner_schedule"
    with patch(f"{_MODULE}.should_run_cron", return_value=True), \
         patch(f"{_MODULE}.claim_pending_manual_run", return_value=manual_claimed):
        handler = AutoDevRunnerScheduler()
        result = handler.claim_run(session, sched, svc, ctx)

    assert result is manual_claimed


# ── T3: manual run claim 통합 경로 (실제 DB 레이어) ──────────────────────────

def test_t3_real_manual_run_claimed_from_db(session):
    """DB에 worker_id='manual' run 생성 → claim_pending_manual_run이 소비하고 worker_id 갱신"""
    from app.services.task_schedule_service import TaskScheduleService
    from app.worker.schedule_handler_base import claim_pending_manual_run

    sched = _make_schedule(session)
    svc = TaskScheduleService(db=session)
    manual_run = svc.start_run(schedule_id=sched.id, worker_id="manual")
    session.commit()

    ctx = _make_ctx(session)
    result = claim_pending_manual_run(session, sched, svc, ctx, "auto_dev_runner")

    assert result is not None
    assert result.run.id == manual_run.id
    assert result.run.worker_id == ctx.worker_name  # "test-worker"로 갱신


def test_t3_manual_run_prior_to_cron_in_claim_run(session):
    """manual run + cron 동시 발생 → manual run 먼저 소비, cron 경로(start_claimed_run) 미호출"""
    from app.services.task_schedule_service import TaskScheduleService

    sched = _make_schedule(session)
    svc = TaskScheduleService(db=session)
    manual_run = svc.start_run(schedule_id=sched.id, worker_id="manual")
    session.commit()

    ctx = _make_ctx(session)

    _MODULE = "app.modules.dev_runner.schedulers.auto_dev_runner_schedule"
    with patch(f"{_MODULE}.should_run_cron", return_value=True), \
         patch(f"{_MODULE}.start_claimed_run") as mock_start:
        handler = AutoDevRunnerScheduler()
        result = handler.claim_run(session, sched, svc, ctx)

    mock_start.assert_not_called()
    assert result is not None
    assert result.run.id == manual_run.id


# ── execute ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_returns_outcome_with_counts():
    """execute → HandlerRunOutcome with collected_count"""
    handler = AutoDevRunnerScheduler()
    sched = MagicMock()
    claimed = MagicMock()
    ctx = MagicMock()

    fake_runs = [
        {"status": "completed"},
        {"status": "failed"},
        {"status": "skipped"},
    ]

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._scan_and_run_plans",
               new=AsyncMock(return_value=fake_runs)):
        outcome = await handler.execute(sched, claimed, ctx)

    assert outcome.collected_count == 3
    assert outcome.saved_count == 1
    assert outcome.config_snapshot_patch["completed"] == 1
    assert outcome.config_snapshot_patch["failed"] == 1
    assert outcome.config_snapshot_patch["skipped"] == 1
