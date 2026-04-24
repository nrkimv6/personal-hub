"""Plan archive scheduler contract tests."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.schedulers.plan_archive_schedule import PlanArchiveScheduler
from app.worker.schedule_handler_base import WorkerContext


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    LLMRequest.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()


def _make_ctx(session_factory):
    return WorkerContext(
        worker_name="test_worker",
        browser_manager=None,
        db_factory=session_factory,
    )


class TestPlanArchiveClaimRun:
    def test_claim_run_starts_run_when_cron_due(self, session_factory):
        scheduler = PlanArchiveScheduler()
        db = session_factory()
        schedule = MagicMock(id=1)
        svc = MagicMock()
        run = MagicMock(id=10)
        svc.get_latest_run.return_value = None
        svc.has_active_run.return_value = False
        svc.start_run.return_value = run

        with patch(
            "app.modules.dev_runner.schedulers.plan_archive_schedule.should_run_cron",
            return_value=True,
        ):
            claimed = scheduler.claim_run(db, schedule, svc, _make_ctx(session_factory))

        assert claimed is not None
        assert claimed.run is run
        assert claimed.task_name == "plan_archive_analyze_1_run_10"
        svc.start_run.assert_called_once_with(
            schedule_id=1,
            worker_id="test_worker",
            config_snapshot={},
        )
        db.close()

    def test_claim_run_skips_when_cron_not_due(self, session_factory):
        scheduler = PlanArchiveScheduler()
        db = session_factory()
        schedule = MagicMock(id=1)
        svc = MagicMock()
        svc.get_latest_run.return_value = None

        with patch(
            "app.modules.dev_runner.schedulers.plan_archive_schedule.should_run_cron",
            return_value=False,
        ):
            claimed = scheduler.claim_run(db, schedule, svc, _make_ctx(session_factory))

        assert claimed is None
        svc.start_run.assert_not_called()
        db.close()


class TestPlanArchiveProcessHelper:
    def test_enqueue_unprocessed_plans_creates_requests_from_db_content(self, session_factory):
        with session_factory() as db:
            db.add(
                PlanRecord(
                    filename_hash="hash-1",
                    file_path="/archive/2026-04-24_plan.md",
                    raw_content="# plan archive\ncontent",
                    archived_at=datetime(2026, 4, 24),
                    llm_processed_at=None,
                )
            )
            db.commit()

        fake_llm = MagicMock()
        fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

        with patch(
            "app.modules.dev_runner.schedulers.plan_archive_schedule.LLMService",
            return_value=fake_llm,
        ), patch(
            "app.modules.dev_runner.schedulers.plan_archive_schedule.build_plan_analyze_prompt",
            side_effect=lambda file_content, filename: f"{filename}::{file_content}",
        ):
            count = PlanArchiveScheduler._enqueue_unprocessed_plans(session_factory)

        assert count == 1
        with session_factory() as db:
            request = db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").first()
            assert request is not None
            assert "2026-04-24_plan.md" in request.prompt
            assert "# plan archive" in request.prompt

    def test_enqueue_unprocessed_plans_skips_when_content_missing(self, session_factory):
        with session_factory() as db:
            db.add(
                PlanRecord(
                    filename_hash="hash-empty",
                    file_path="/missing/2026-04-24_plan.md",
                    raw_content=None,
                    archived_at=datetime(2026, 4, 24),
                    llm_processed_at=None,
                )
            )
            db.commit()

        fake_llm = MagicMock()
        fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

        with patch(
            "app.modules.dev_runner.schedulers.plan_archive_schedule.LLMService",
            return_value=fake_llm,
        ):
            count = PlanArchiveScheduler._enqueue_unprocessed_plans(session_factory)

        assert count == 0
        with session_factory() as db:
            assert db.query(LLMRequest).count() == 0


class TestPlanArchiveExecute:
    @pytest.mark.asyncio
    async def test_execute_returns_counts_only_outcome(self, session_factory):
        scheduler = PlanArchiveScheduler()
        schedule = MagicMock(id=1)
        claimed = MagicMock()

        with patch.object(
            PlanArchiveScheduler,
            "_enqueue_unprocessed_plans",
            return_value=3,
        ):
            outcome = await scheduler.execute(schedule, claimed, _make_ctx(session_factory))

        assert outcome.collected_count == 3
        assert outcome.saved_count == 3
        assert outcome.stop_reason == "completed"
        assert outcome.config_snapshot_patch == {"queued": 3}
