"""Unit tests for scripts/migrations/backfill_workflows_sqlite_to_pg.py."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, func, insert, select

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "migrations"))
sys.path.insert(0, str(REPO_ROOT))

import backfill_workflows_sqlite_to_pg as m  # noqa: E402
from app.models.workflow import Workflow as WorkflowModel  # noqa: E402


def _seed_engine(path: Path):
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    WorkflowModel.__table__.create(bind=engine, checkfirst=True)
    return engine


def _seed_rows(engine, rows: list[dict]) -> None:
    with engine.begin() as conn:
        conn.execute(insert(WorkflowModel.__table__), rows)


def test_normalize_row_treats_datetime_strings_and_objects_equally():
    row_a = {
        "id": 1,
        "slug": "demo",
        "created_at": datetime(2026, 4, 16, 12, 0, 0),
        "started_at": None,
        "merged_at": None,
        "finished_at": None,
        "plan_file": None,
        "branch": None,
        "runner_id": None,
        "status": "planned",
        "engine": None,
        "error_message": None,
        "commit_hash": None,
        "worktree_path": None,
    }
    row_b = dict(row_a)
    row_b["created_at"] = "2026-04-16 12:00:00"
    assert m._normalize_row(row_a) == m._normalize_row(row_b)


def test_run_dry_run_reports_planned_inserts(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "sqlite.db"
    pg_path = tmp_path / "pg.db"
    source_engine = _seed_engine(sqlite_path)
    target_engine = _seed_engine(pg_path)

    try:
        _seed_rows(
            source_engine,
            [
                {
                    "id": 1,
                    "slug": "demo-1",
                    "plan_file": "docs/plan/demo.md",
                    "branch": None,
                    "runner_id": None,
                    "status": "planned",
                    "engine": None,
                    "error_message": None,
                    "commit_hash": None,
                    "worktree_path": None,
                    "created_at": datetime(2026, 4, 16, 12, 0, 0),
                    "started_at": None,
                    "merged_at": None,
                    "finished_at": None,
                }
            ],
        )

        monkeypatch.setattr(m, "_make_pg_engine", lambda _pg_url: target_engine)
        monkeypatch.setattr(m, "_sync_workflow_sequence", lambda _conn: None)

        result = m.run(
            sqlite_path=sqlite_path,
            pg_url="postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor",
            apply=False,
        )

        assert result["applied"] is False
        assert result["planned_inserted"] == 1
        with target_engine.connect() as conn:
            count = conn.execute(select(func.count()).select_from(WorkflowModel.__table__)).scalar()
        assert count == 0
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_run_apply_inserts_missing_rows_and_skips_identical_rows(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "sqlite.db"
    pg_path = tmp_path / "pg.db"
    source_engine = _seed_engine(sqlite_path)
    target_engine = _seed_engine(pg_path)

    row_existing = {
        "id": 1,
        "slug": "demo-1",
        "plan_file": "docs/plan/demo.md",
        "branch": None,
        "runner_id": None,
        "status": "planned",
        "engine": None,
        "error_message": None,
        "commit_hash": None,
        "worktree_path": None,
        "created_at": datetime(2026, 4, 16, 12, 0, 0),
        "started_at": None,
        "merged_at": None,
        "finished_at": None,
    }
    row_missing = {
        "id": 2,
        "slug": "demo-2",
        "plan_file": "docs/plan/demo-2.md",
        "branch": None,
        "runner_id": None,
        "status": "running",
        "engine": "claude",
        "error_message": None,
        "commit_hash": None,
        "worktree_path": None,
        "created_at": datetime(2026, 4, 16, 13, 0, 0),
        "started_at": datetime(2026, 4, 16, 13, 5, 0),
        "merged_at": None,
        "finished_at": None,
    }

    try:
        _seed_rows(source_engine, [row_existing, row_missing])
        _seed_rows(target_engine, [dict(row_existing)])

        monkeypatch.setattr(m, "_make_pg_engine", lambda _pg_url: target_engine)
        monkeypatch.setattr(m, "_sync_workflow_sequence", lambda _conn: None)

        result = m.run(
            sqlite_path=sqlite_path,
            pg_url="postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor",
            apply=True,
        )

        assert result["applied"] is True
        assert result["inserted"] == 1
        assert result["skipped"] == 1

        with target_engine.connect() as conn:
            rows = conn.execute(
                select(WorkflowModel.__table__).order_by(WorkflowModel.__table__.c.id)
            ).mappings().all()
        assert len(rows) == 2
        assert rows[1]["slug"] == "demo-2"
        assert rows[1]["status"] == "running"
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_run_stops_on_conflict_without_writing(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "sqlite.db"
    pg_path = tmp_path / "pg.db"
    source_engine = _seed_engine(sqlite_path)
    target_engine = _seed_engine(pg_path)

    row_source = {
        "id": 1,
        "slug": "demo-1",
        "plan_file": "docs/plan/demo.md",
        "branch": None,
        "runner_id": None,
        "status": "planned",
        "engine": None,
        "error_message": None,
        "commit_hash": None,
        "worktree_path": None,
        "created_at": datetime(2026, 4, 16, 12, 0, 0),
        "started_at": None,
        "merged_at": None,
        "finished_at": None,
    }
    row_conflict = dict(row_source)
    row_conflict["slug"] = "different"

    try:
        _seed_rows(source_engine, [row_source])
        _seed_rows(target_engine, [row_conflict])

        monkeypatch.setattr(m, "_make_pg_engine", lambda _pg_url: target_engine)
        monkeypatch.setattr(m, "_sync_workflow_sequence", lambda _conn: None)

        result = m.run(
            sqlite_path=sqlite_path,
            pg_url="postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor",
            apply=True,
        )

        assert result["conflicts"] == 1
        with target_engine.connect() as conn:
            count = conn.execute(select(func.count()).select_from(WorkflowModel.__table__)).scalar()
        assert count == 1
    finally:
        source_engine.dispose()
        target_engine.dispose()
