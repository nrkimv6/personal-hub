"""Plan Archive health integration contracts with a real DB session."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.plan_record import PlanRecord, PlanEvent
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
    temp = svc.ingest_single(
        r"C:\Users\Narang\AppData\Local\Temp\pytest-of-Narang\pytest-9\docs\archive\2026-05-05_temp-plan.md",
        raw_content="# temp",
    )
    schedule = TaskSchedule(
        name="plan_archive_analyze_daily",
        target_type=TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE,
        schedule_type="cron",
        schedule_value='{"time":"02:10"}',
        enabled=False,
    )
    db.add(schedule)
    db.flush()
    db.add_all([
        LLMRequest(caller_type="plan_archive_analyze", caller_id=real.filename_hash, prompt="p", status="pending"),
        LLMRequest(caller_type="plan_archive_analyze", caller_id=temp.filename_hash, prompt="p", status="failed"),
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

    assert health["archived_total"] == 2
    assert health["real_unprocessed"] == 1
    assert health["temp_pytest_unprocessed"] == 1
    assert health["pending_or_processing_requests"] == 1
    assert health["failed_requests"] == 1
    assert health["plan_archive_schedule"]["enabled"] is False


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

    assert status[0]["pending_count"] == 1
    assert "real-plan" in status[0]["pending_archives"][0]["file_path"]
