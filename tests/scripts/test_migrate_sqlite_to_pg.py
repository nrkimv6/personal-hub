"""Unit tests for scripts/migrations/migrate_sqlite_to_pg.py."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "migrations"))
sys.path.insert(0, str(REPO_ROOT))

import migrate_sqlite_to_pg as migrate  # noqa: E402
import verify_writing_migration as verify  # noqa: E402


def _make_sqlite_engine(path: Path):
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    return engine


def test_default_sqlite_path_right():
    expected = REPO_ROOT / "data" / "monitor.db"
    assert migrate.PROJECT_ROOT == REPO_ROOT
    assert migrate._DEFAULT_SQLITE_PATH == expected
    assert "writing_collection_tasks" not in migrate.WRITING_TABLE_SET


def test_get_sqlite_tables_boundary_writing_allowlist(tmp_path):
    db_path = tmp_path / "source.db"
    engine = _make_sqlite_engine(db_path)

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE writing_sources (id INTEGER PRIMARY KEY, content TEXT NOT NULL)"))
            conn.execute(text("CREATE TABLE generated_writings (id INTEGER PRIMARY KEY, content TEXT NOT NULL)"))
            conn.execute(text("CREATE TABLE worker_status (id INTEGER PRIMARY KEY, status TEXT)"))

        tables = migrate.get_sqlite_tables(
            engine,
            selected_tables=["writing_sources", "generated_writings"],
        )
        assert set(tables) == {"writing_sources", "generated_writings"}
        assert "worker_status" not in tables
    finally:
        engine.dispose()


def test_get_sqlite_tables_orders_schedule_before_runs(tmp_path):
    db_path = tmp_path / "source.db"
    engine = _make_sqlite_engine(db_path)

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE task_schedule_runs (id INTEGER PRIMARY KEY, schedule_id INTEGER)"))
            conn.execute(text("CREATE TABLE task_schedules (id INTEGER PRIMARY KEY, target_type TEXT)"))
            conn.execute(text("CREATE TABLE writing_sources (id INTEGER PRIMARY KEY, content TEXT NOT NULL)"))

        tables = migrate.get_sqlite_tables(
            engine,
            selected_tables=["task_schedule_runs", "task_schedules", "writing_sources"],
        )
        assert tables == ["task_schedules", "task_schedule_runs", "writing_sources"]
    finally:
        engine.dispose()


def test_startup_log_reference_exists_sqlite_path(tmp_path):
    sqlite_path = (tmp_path / "monitor.db").resolve()
    banner = migrate.build_startup_banner(
        sqlite_path=sqlite_path,
        sqlite_url=f"sqlite:///{sqlite_path.as_posix()}",
        pg_url="postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor",
        selected_tables=["writing_sources", "generated_writings"],
        dry_run=True,
    )

    assert str(sqlite_path) in banner
    assert "writing_sources, generated_writings" in banner
    assert "DRY RUN" in banner


def test_verify_writing_migration_red_flag_existence(tmp_path):
    sqlite_path = tmp_path / "legacy.db"
    pg_path = tmp_path / "target.db"
    sqlite_engine = _make_sqlite_engine(sqlite_path)
    pg_engine = _make_sqlite_engine(pg_path)

    try:
        with sqlite_engine.begin() as conn:
            conn.execute(text("CREATE TABLE writing_sources (id INTEGER PRIMARY KEY, content TEXT NOT NULL)"))
            conn.execute(text("INSERT INTO writing_sources (id, content) VALUES (1, 'legacy source')"))

        with pg_engine.begin() as conn:
            conn.execute(text("CREATE TABLE writing_sources (id INTEGER PRIMARY KEY, content TEXT NOT NULL)"))

        rows = verify.collect_row_counts(sqlite_engine, pg_engine, ["writing_sources"])
        assert len(rows) == 1
        assert rows[0]["table"] == "writing_sources"
        assert rows[0]["sqlite_count"] == 1
        assert rows[0]["pg_count"] == 0
        assert rows[0]["red_flag"] is True
        assert rows[0]["mismatch"] is True
    finally:
        sqlite_engine.dispose()
        pg_engine.dispose()


def test_verify_writing_target_types_match_task_schedule_constants():
    from app.models.task_schedule import TaskSchedule

    assert verify.WRITING_TARGET_TYPES == (
        TaskSchedule.TARGET_TYPE_WRITING_TASK,
        TaskSchedule.TARGET_TYPE_WRITING_SOURCE_COLLECT,
        TaskSchedule.TARGET_TYPE_KEYWORD_ANALYSIS,
        TaskSchedule.TARGET_TYPE_TOPIC_EXTRACT,
    )
