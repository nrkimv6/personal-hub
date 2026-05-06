from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanEvent, PlanRecord
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.modules.claude_worker.models.llm_request import LLMRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cleanup" / "purge_pytest_temp_plan_records.py"


def _seed_db(tmp_path, count=2):
    db_path = tmp_path / "purge_e2e_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanEvent.__table__.create(bind=engine, checkfirst=True)
    TaskSchedule.__table__.create(bind=engine, checkfirst=True)
    TaskScheduleRun.__table__.create(bind=engine, checkfirst=True)
    LLMRequest.__table__.create(bind=engine, checkfirst=True)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    for idx in range(count):
        row = PlanRecord(
            filename_hash=f"temp_{idx}",
            file_path=f"/tmp/pytest-of-user/pytest-{idx}/docs/archive/temp.md",
            status="archived",
        )
        session.add(row)
    session.commit()
    return db_path


def _run(*args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        env=env,
        capture_output=True,
        check=False,
    )


def test_cli_dry_run_json_shape(tmp_path):
    db_path = _seed_db(tmp_path, count=1)

    result = _run("--database-url", f"sqlite:///{db_path}", "--json")

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["dry_run"] is True
    assert data["candidate_count"] == 1
    assert "examples" in data


def test_cli_confirm_limit_deletes_one_candidate(tmp_path):
    db_path = _seed_db(tmp_path, count=2)

    first = _run("--database-url", f"sqlite:///{db_path}", "--confirm", "--limit", "1", "--json")
    second = _run("--database-url", f"sqlite:///{db_path}", "--json")

    assert first.returncode == 0
    assert json.loads(first.stdout)["plan_records_deleted"] == 1
    assert json.loads(second.stdout)["candidate_count"] == 1


def test_cli_production_like_confirm_requires_allow_flag():
    result = _run(
        "--database-url",
        "postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor",
        "--confirm",
        "--json",
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "PRODUCTION_CONFIRM_REQUIRES_ALLOW_PRODUCTION"
