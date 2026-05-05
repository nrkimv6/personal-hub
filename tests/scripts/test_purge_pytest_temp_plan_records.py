from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "cleanup"))

import purge_pytest_temp_plan_records as purge  # noqa: E402
from app.models.plan_record import PlanEvent, PlanRecord  # noqa: E402
from app.models.task_schedule import TaskSchedule, TaskScheduleRun  # noqa: E402
from app.modules.claude_worker.models.llm_request import LLMRequest  # noqa: E402


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test_purge.db'}", connect_args={"check_same_thread": False})
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanEvent.__table__.create(bind=engine, checkfirst=True)
    TaskSchedule.__table__.create(bind=engine, checkfirst=True)
    TaskScheduleRun.__table__.create(bind=engine, checkfirst=True)
    LLMRequest.__table__.create(bind=engine, checkfirst=True)
    return engine


def _session(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def _seed(session, *, temp_count=1, non_temp_count=1):
    for idx in range(temp_count):
        record = PlanRecord(
            filename_hash=f"temp_hash_{idx}",
            file_path=rf"C:\Users\Narang\AppData\Local\Temp\pytest-of-Narang\pytest-{idx}\docs\archive\temp.md",
            status="archived",
        )
        session.add(record)
        session.flush()
        session.add(PlanEvent(plan_record_id=record.id, event_type="created"))
        session.add(LLMRequest(caller_type="plan_archive_analyze", caller_id=record.filename_hash, prompt="p"))
    for idx in range(non_temp_count):
        record = PlanRecord(
            filename_hash=f"real_hash_{idx}",
            file_path=rf"D:\work\project\tools\monitor-page\.worktrees\plans\docs\archive\real-{idx}.md",
            status="archived",
        )
        session.add(record)
    session.commit()


def test_dry_run_right_reports_candidates_without_mutation(tmp_path):
    engine = _engine(tmp_path)
    session = _session(engine)
    _seed(session, temp_count=2)

    summary = purge.run(database_url=f"sqlite:///{tmp_path / 'test_purge.db'}", confirm=False, allow_production=False, limit=None)

    assert summary["dry_run"] is True
    assert summary["candidate_count"] == 2
    assert summary["plan_event_count"] == 2
    assert summary["llm_request_count"] == 2
    assert session.query(PlanRecord).count() == 3
    assert session.query(PlanEvent).count() == 2


def test_dry_run_boundary_no_candidates_returns_zero_counts(tmp_path):
    engine = _engine(tmp_path)
    _seed(_session(engine), temp_count=0, non_temp_count=1)

    summary = purge.run(database_url=f"sqlite:///{tmp_path / 'test_purge.db'}", confirm=False, allow_production=False, limit=None)

    assert summary["candidate_count"] == 0
    assert summary["plan_event_count"] == 0
    assert summary["llm_request_count"] == 0


def test_confirm_right_deletes_plan_events_before_plan_records(tmp_path):
    engine = _engine(tmp_path)
    session = _session(engine)
    _seed(session, temp_count=1, non_temp_count=1)

    summary = purge.run(
        database_url=f"sqlite:///{tmp_path / 'test_purge.db'}",
        confirm=True,
        allow_production=False,
        limit=None,
    )

    assert summary["plan_events_deleted"] == 1
    assert summary["plan_records_deleted"] == 1
    assert session.query(PlanRecord).filter(PlanRecord.filename_hash.like("temp%")).count() == 0
    assert session.query(PlanRecord).filter(PlanRecord.filename_hash.like("real%")).count() == 1


def test_confirm_error_refuses_without_confirm_flag(tmp_path):
    summary = purge.run(
        database_url="postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor",
        confirm=True,
        allow_production=False,
        limit=None,
    )

    assert summary["error"] == "PRODUCTION_CONFIRM_REQUIRES_ALLOW_PRODUCTION"


def test_confirm_error_preserves_non_temp_plan_records(tmp_path):
    engine = _engine(tmp_path)
    session = _session(engine)
    _seed(session, temp_count=1, non_temp_count=2)

    purge.run(
        database_url=f"sqlite:///{tmp_path / 'test_purge.db'}",
        confirm=True,
        allow_production=False,
        limit=None,
    )

    assert session.query(PlanRecord).count() == 2
    assert all("pytest" not in row.file_path.lower() for row in session.query(PlanRecord).all())
