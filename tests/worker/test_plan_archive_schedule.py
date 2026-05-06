"""Plan archive scheduler contract tests."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.plan_record import PlanRecord
from app.models.plan_archive_execution import PlanArchiveExecutionAttempt, PlanArchiveExecutionJob
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
    PlanArchiveExecutionJob.__table__.create(bind=engine, checkfirst=True)
    PlanArchiveExecutionAttempt.__table__.create(bind=engine, checkfirst=True)
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
        assert claimed.run_id == run.id
        assert claimed.schedule_id == 1
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
            "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
            return_value=fake_llm,
        ):
            stats = PlanArchiveScheduler._enqueue_unprocessed_plans(session_factory)

        assert stats["queued"] == 1
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
            "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
            return_value=fake_llm,
        ):
            stats = PlanArchiveScheduler._enqueue_unprocessed_plans(session_factory)

        assert stats["queued"] == 0
        assert stats["skipped_empty"] == 1
        with session_factory() as db:
            assert db.query(LLMRequest).count() == 0

    def test_enqueue_unprocessed_skips_temp_pytest_records_by_default(self, session_factory):
        with session_factory() as db:
            db.add_all([
                PlanRecord(
                    filename_hash="hash-real",
                    file_path="/archive/2026-04-24_real.md",
                    raw_content="# real",
                    archived_at=datetime(2026, 4, 24),
                    llm_processed_at=None,
                ),
                PlanRecord(
                    filename_hash="hash-temp",
                    file_path=r"C:\Users\Narang\AppData\Local\Temp\pytest-of-Narang\pytest-42\docs\archive\2026-04-24_temp.md",
                    raw_content="# temp",
                    archived_at=datetime(2026, 4, 24),
                    llm_processed_at=None,
                ),
            ])
            db.commit()

        fake_llm = MagicMock()
        fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")
        with patch(
            "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
            return_value=fake_llm,
        ):
            stats = PlanArchiveScheduler._enqueue_unprocessed_plans(session_factory)

        assert stats["queued"] == 1
        assert stats["skipped_temp"] == 1
        with session_factory() as db:
            request = db.query(LLMRequest).one()
            assert request.caller_id == "hash-real"

    def test_enqueue_unprocessed_respects_max_backfill_per_run_boundary(self, session_factory):
        with session_factory() as db:
            for idx in range(3):
                db.add(
                    PlanRecord(
                        filename_hash=f"hash-{idx}",
                        file_path=f"/archive/2026-04-2{idx}_plan.md",
                        raw_content=f"# plan {idx}",
                        archived_at=datetime(2026, 4, 20 + idx),
                        llm_processed_at=None,
                    )
                )
            db.commit()

        fake_llm = MagicMock()
        fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")
        with patch(
            "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
            return_value=fake_llm,
        ):
            stats = PlanArchiveScheduler._enqueue_unprocessed_plans(
                session_factory,
                {"max_backfill_per_run": 2},
            )

        assert stats["queued"] == 2
        assert stats["remaining_real_unprocessed"] == 1
        with session_factory() as db:
            assert db.query(LLMRequest).count() == 2

    def test_enqueue_unprocessed_skips_processing_request_duplicate(self, session_factory):
        with session_factory() as db:
            db.add(
                PlanRecord(
                    filename_hash="hash-processing",
                    file_path="/archive/2026-04-24_processing.md",
                    raw_content="# processing",
                    archived_at=datetime(2026, 4, 24),
                    llm_processed_at=None,
                )
            )
            db.add(
                LLMRequest(
                    caller_type="plan_archive_analyze",
                    caller_id="hash-processing",
                    prompt="existing",
                    status="processing",
                )
            )
            db.commit()

        fake_llm = MagicMock()
        fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")
        with patch(
            "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
            return_value=fake_llm,
        ):
            stats = PlanArchiveScheduler._enqueue_unprocessed_plans(session_factory)

        assert stats["queued"] == 0
        assert stats["skipped_active_request"] == 1
        with session_factory() as db:
            assert db.query(LLMRequest).count() == 1


class TestPlanArchiveExecute:
    @pytest.mark.asyncio
    async def test_execute_returns_counts_only_outcome(self, session_factory):
        scheduler = PlanArchiveScheduler()
        schedule = MagicMock(id=1)
        claimed = MagicMock()

        with patch.object(
            PlanArchiveScheduler,
            "_enqueue_unprocessed_plans",
            return_value={
                "queued": 3,
                "skipped_temp": 0,
                "skipped_empty": 0,
                "skipped_active_request": 0,
                "remaining_real_unprocessed": 0,
            },
        ):
            outcome = await scheduler.execute(schedule, claimed, _make_ctx(session_factory))

        assert outcome.collected_count == 3
        assert outcome.saved_count == 3
        assert outcome.stop_reason == "completed"
        assert outcome.config_snapshot_patch["queued"] == 3
        assert outcome.config_snapshot_patch["skipped_temp"] == 0
        assert outcome.config_snapshot_patch["skipped_empty"] == 0
        assert outcome.config_snapshot_patch["skipped_active_request"] == 0
        assert outcome.config_snapshot_patch["remaining_real_unprocessed"] == 0
        assert outcome.config_snapshot_patch == {
            "queued": 3,
            "skipped_temp": 0,
            "skipped_empty": 0,
            "skipped_active_request": 0,
            "remaining_real_unprocessed": 0,
        }
