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


def _prepare(tmp_path):
    db_path = tmp_path / "integration.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanEvent.__table__.create(bind=engine, checkfirst=True)
    TaskSchedule.__table__.create(bind=engine, checkfirst=True)
    TaskScheduleRun.__table__.create(bind=engine, checkfirst=True)
    LLMRequest.__table__.create(bind=engine, checkfirst=True)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    temp = PlanRecord(
        filename_hash="temp_hash",
        file_path="/tmp/pytest-of-user/pytest-1/docs/archive/temp.md",
        status="archived",
    )
    real = PlanRecord(
        filename_hash="real_hash",
        file_path="/repo/.worktrees/plans/docs/archive/real.md",
        status="archived",
    )
    session.add_all([temp, real])
    session.flush()
    session.add(PlanEvent(plan_record_id=temp.id, event_type="created"))
    session.add(PlanEvent(plan_record_id=real.id, event_type="created"))
    request = LLMRequest(caller_type="plan_archive_analyze", caller_id=temp.filename_hash, prompt="p")
    session.add(request)
    session.commit()
    return db_path, engine, session, request.id


def test_temp_rows_survive_dry_run_then_confirm_removes_only_temp(tmp_path):
    db_path, _engine, session, _request_id = _prepare(tmp_path)
    url = f"sqlite:///{db_path}"

    dry = purge.run(database_url=url, confirm=False, allow_production=False, limit=None)
    assert dry["candidate_count"] == 1
    assert session.query(PlanRecord).count() == 2
    assert session.query(PlanEvent).count() == 2

    confirmed = purge.run(database_url=url, confirm=True, allow_production=False, limit=None)
    assert confirmed["plan_records_deleted"] == 1
    assert session.query(PlanRecord).count() == 1
    assert session.query(PlanRecord).one().filename_hash == "real_hash"
    assert session.query(PlanEvent).count() == 1


def test_linked_llm_request_soft_delete_matches_summary(tmp_path):
    db_path, _engine, session, request_id = _prepare(tmp_path)

    summary = purge.run(database_url=f"sqlite:///{db_path}", confirm=True, allow_production=False, limit=None)

    request = session.query(LLMRequest).filter_by(id=request_id).one()
    assert summary["llm_requests_soft_deleted"] == 1
    assert request.deleted_at is not None
