"""Plan Archive health integration contracts with a real DB session."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.plan_record import (
    PlanRecord,
    PlanEvent,
    PlanRecordChunk,
    PlanRecordFileRef,
    PlanRecordRelation,
    PlanRecordSearchRun,
)
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.routes.plan_records import get_archive_health, get_guide_status
from app.modules.dev_runner.services.plan_record_service import PlanRecordService


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanEvent.__table__.create(bind=engine, checkfirst=True)
    TaskSchedule.__table__.create(bind=engine, checkfirst=True)
    TaskScheduleRun.__table__.create(bind=engine, checkfirst=True)
    LLMRequest.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_archive_health(db):
    svc = PlanRecordService(db)
    real = svc.ingest_single("/repo/docs/archive/2026-05-05_real-plan.md", raw_content="# real")
    older = svc.ingest_single("/repo/docs/archive/2026-05-01_older-plan.md", raw_content="# older")
    temp = svc.ingest_single(
        r"C:\Users\Narang\AppData\Local\Temp\pytest-of-Narang\pytest-9\docs\archive\2026-05-05_temp-plan.md",
        raw_content="# temp",
    )
    real.archived_at = datetime(2026, 5, 5, 1, 0)
    older.archived_at = datetime(2026, 5, 1, 9, 30)
    temp.archived_at = datetime(2026, 5, 5, 3, 0)
    schedule = TaskSchedule(
        name="plan_archive_analyze_daily",
        target_type=TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE,
        schedule_type="cron",
        schedule_value='{"time":"02:10"}',
        enabled=False,
        last_run_at=datetime(2026, 5, 5, 2, 10),
    )
    db.add(schedule)
    db.flush()
    db.add_all([
        LLMRequest(
            caller_type="plan_archive_analyze",
            caller_id=real.filename_hash,
            prompt="p",
            status="pending",
            requested_at=datetime(2026, 5, 5, 2, 11),
            provider="claude",
            model="opus",
        ),
        LLMRequest(
            caller_type="plan_archive_analyze",
            caller_id=older.filename_hash,
            prompt="p",
            status="processing",
            requested_at=datetime(2026, 5, 5, 2, 13),
            provider="gemini",
            model="pro",
        ),
        LLMRequest(
            caller_type="plan_archive_analyze",
            caller_id=temp.filename_hash,
            prompt="p",
            status="failed",
            requested_at=datetime(2026, 5, 5, 2, 14),
            error_message="quota reset wait",
        ),
        LLMRequest(
            caller_type="plan_archive_analyze",
            caller_id="completed-is-not-active",
            prompt="p",
            status="completed",
            requested_at=datetime(2026, 5, 5, 2, 15),
        ),
        TaskScheduleRun(
            schedule_id=schedule.id,
            status=TaskScheduleRun.STATUS_COMPLETED,
            finished_at=datetime(2026, 5, 4, 2, 12),
        ),
        TaskScheduleRun(
            schedule_id=schedule.id,
            status=TaskScheduleRun.STATUS_FAILED,
            finished_at=datetime(2026, 5, 5, 2, 12),
        ),
    ])
    db.flush()


def test_get_archive_health_route_right_counts(db):
    """T3: route-level health separates real/temp/pending/failed records."""
    _seed_archive_health(db)

    health = get_archive_health(db=db)

    assert health["archived_total"] == 3
    assert health["real_unprocessed"] == 2
    assert health["temp_pytest_unprocessed"] == 1
    assert health["pending_or_processing_requests"] == 2
    assert health["failed_requests"] == 1
    assert health["oldest_unprocessed_at"] == datetime(2026, 5, 1, 9, 30).isoformat()
    assert health["latest_failed_request"]["requested_at"] == datetime(2026, 5, 5, 2, 14).isoformat()
    assert health["latest_failed_request"]["error_message"] == "quota reset wait"
    assert health["plan_archive_schedule"]["enabled"] is False
    assert health["plan_archive_schedule"]["last_run"] == datetime(2026, 5, 5, 2, 10).isoformat()
    assert health["plan_archive_schedule"]["last_success"] == datetime(2026, 5, 4, 2, 12).isoformat()
    assert health["retrieval_db_readiness"]["ok"] is False
    assert "plan_record_file_refs" in health["retrieval_db_readiness"]["missing_tables"]


def test_get_archive_health_route_right_readiness_ok(db):
    """T3: route-level health reports retrieval DB readiness when tables exist."""
    for table in [
        PlanRecordChunk.__table__,
        PlanRecordFileRef.__table__,
        PlanRecordRelation.__table__,
        PlanRecordSearchRun.__table__,
    ]:
        table.create(bind=db.get_bind(), checkfirst=True)
    _seed_archive_health(db)

    health = get_archive_health(db=db)

    assert health["retrieval_db_readiness"]["ok"] is True
    assert health["retrieval_db_readiness"]["missing_tables"] == []


def test_get_guide_status_route_excludes_temp_archive(db, monkeypatch):
    """T3: guide-status route does not count pytest temp archive as pending guide work."""
    from app.shared import wiki_tags

    monkeypatch.setattr(wiki_tags, "load_meta_yaml", lambda: {
        "dev-guide": {"owns_archive_tags": ["plan"], "last_archive_scan": "2026-05-01"}
    })
    monkeypatch.setattr(wiki_tags, "load_whitelist", lambda: {"plan"})
    monkeypatch.setattr(wiki_tags, "extract_wiki_tags", lambda filename, whitelist: ["plan"])
    _seed_archive_health(db)

    status = get_guide_status(db=db)

    assert status[0]["pending_count"] == 2
    pending_paths = [item["file_path"] for item in status[0]["pending_archives"]]
    assert any("real-plan" in path for path in pending_paths)
    assert any("older-plan" in path for path in pending_paths)
