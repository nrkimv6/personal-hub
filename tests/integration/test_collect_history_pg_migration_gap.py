"""Integration tests for writing SQLite→PG migration gap recovery."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import sessionmaker

try:
    import psycopg2
    from psycopg2 import sql

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "migrations"))
sys.path.insert(0, str(REPO_ROOT))

import migrate_sqlite_to_pg as migrate  # noqa: E402
import verify_writing_migration as verify  # noqa: E402
from app.models.base import Base as AppBase  # noqa: E402
from app.models.task_schedule import TaskSchedule, TaskScheduleRun  # noqa: E402
from app.models.writing import WritingSource  # noqa: E402
from app.models.writing_element import WritingElement  # noqa: E402
from app.modules.claude_worker.models.llm_request import LLMRequest  # noqa: E402
from app.modules.writing.models.writing_batch import WritingBatch  # noqa: E402
from app.modules.writing.worker.writing_worker import WritingWorker  # noqa: E402
from app.services.collect_service import CollectService  # noqa: E402


BASE_PG_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor",
)
TEST_SCHEMA = "test_collect_history_pg_gap"


def _replace_search_path(db_url: str, search_path: str) -> str:
    parsed = urlsplit(db_url)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    filtered_pairs = [(key, value) for key, value in query_pairs if key != "options"]
    filtered_pairs.append(("options", f"-csearch_path={search_path}"))
    return urlunsplit(parsed._replace(query=urlencode(filtered_pairs)))


def _remove_search_path(db_url: str) -> str:
    parsed = urlsplit(db_url)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    filtered_pairs = [(key, value) for key, value in query_pairs if not (key == "options" and "search_path=" in value)]
    return urlunsplit(parsed._replace(query=urlencode(filtered_pairs)))


def _prepare_pg_schema(db_url: str) -> None:
    if not HAS_PSYCOPG2:
        pytest.skip("psycopg2가 없어 PG integration test를 실행할 수 없습니다.")

    conn = psycopg2.connect(_remove_search_path(db_url))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(TEST_SCHEMA)
                )
            )
            cur.execute(
                sql.SQL("CREATE SCHEMA {}").format(
                    sql.Identifier(TEST_SCHEMA)
                )
            )
    finally:
        conn.close()


def _pg_engine():
    pg_url = _replace_search_path(BASE_PG_URL, TEST_SCHEMA)
    _prepare_pg_schema(pg_url)
    return create_engine(pg_url, pool_pre_ping=True)


def _sqlite_engine(path: Path):
    return create_engine(f"sqlite:///{path.as_posix()}")


def _create_tables(engine, table_names: list[str]) -> None:
    tables = [AppBase.metadata.tables[name] for name in table_names]
    AppBase.metadata.create_all(bind=engine, tables=tables)


def _seed_sqlite_legacy(sqlite_engine) -> None:
    _create_tables(sqlite_engine, ["task_schedules", "task_schedule_runs", "writing_sources"])
    with sqlite_engine.begin() as conn:
        conn.execute(
            insert(TaskSchedule.__table__),
            [
                {
                    "id": 1,
                    "name": "writing_task_default",
                    "display_name": "매일 새벽 6시 글쓰기",
                    "target_type": "writing_task",
                    "schedule_type": "time_window",
                    "schedule_value": "{}",
                    "enabled": True,
                }
            ],
        )
        conn.execute(
            insert(TaskScheduleRun.__table__),
            [
                {
                    "id": 1,
                    "schedule_id": 1,
                    "status": "failed",
                    "started_at": datetime(2026, 4, 20, 9, 19, 0),
                    "finished_at": datetime(2026, 4, 20, 9, 19, 0),
                    "error_message": "소스 글이 부족합니다: 0개 (최소 3개 필요)",
                }
            ],
        )
        conn.execute(
            insert(WritingSource.__table__),
            [
                {"id": 1, "content": "legacy source 1", "category": "legacy"},
                {"id": 2, "content": "legacy source 2", "category": "legacy"},
                {"id": 3, "content": "legacy source 3", "category": "legacy"},
            ],
        )


def _seed_pg_runtime_tables(pg_engine) -> sessionmaker:
    _create_tables(
        pg_engine,
        [
            "task_schedules",
            "task_schedule_runs",
            "writing_sources",
            "writing_elements",
            "writing_batches",
            "llm_requests",
        ],
    )
    return sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)


@pytest.fixture
def migration_env(tmp_path):
    sqlite_path = tmp_path / "legacy.db"
    sqlite_engine = _sqlite_engine(sqlite_path)
    pg_engine = _pg_engine()
    PgSession = _seed_pg_runtime_tables(pg_engine)
    _seed_sqlite_legacy(sqlite_engine)

    try:
        yield {
            "sqlite_path": sqlite_path,
            "sqlite_engine": sqlite_engine,
            "pg_engine": pg_engine,
            "pg_sessionmaker": PgSession,
        }
    finally:
        sqlite_engine.dispose()
        pg_engine.dispose()


def _seed_pg_schedule(session) -> TaskSchedule:
    schedule = TaskSchedule(
        name="writing_task_pg_runtime",
        display_name="PG writing runtime",
        target_type="writing_task",
        schedule_type="time_window",
        schedule_value="{}",
        enabled=True,
    )
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    return schedule


def _run_targeted_backfill(env) -> None:
    pg_tables = migrate.get_pg_tables(env["pg_engine"])
    tables = migrate.get_sqlite_tables(
        env["sqlite_engine"],
        selected_tables=["writing_sources", "task_schedules", "task_schedule_runs"],
    )
    missing = [table for table in tables if table not in pg_tables]
    if missing:
        migrate.create_missing_tables_from_sqlite(env["sqlite_engine"], env["pg_engine"], missing)

    for table in tables:
        migrate.migrate_table(
            env["sqlite_engine"],
            env["pg_engine"],
            table,
            allow_existing_rows=True,
        )
    migrate.sync_sequences(env["pg_engine"])


def test_verify_writing_gap_detects_missing_pg_rows(migration_env):
    rows = verify.collect_row_counts(
        migration_env["sqlite_engine"],
        migration_env["pg_engine"],
        ["writing_sources", "task_schedules", "task_schedule_runs"],
    )

    row_map = {row["table"]: row for row in rows}
    assert row_map["writing_sources"]["sqlite_count"] == 3
    assert row_map["writing_sources"]["pg_count"] == 0
    assert row_map["writing_sources"]["red_flag"] is True
    assert row_map["task_schedules"]["mismatch"] is True
    assert row_map["task_schedule_runs"]["mismatch"] is True


def test_writing_worker_fails_with_zero_pg_sources_before_backfill(migration_env):
    session = migration_env["pg_sessionmaker"]()
    try:
        schedule = _seed_pg_schedule(session)
        run = TaskScheduleRun(schedule_id=schedule.id, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)

        worker = WritingWorker(session, project_root=REPO_ROOT)
        result = worker.run(schedule, run)
        session.refresh(run)

        assert run.status == TaskScheduleRun.STATUS_FAILED
        assert run.stop_reason == "source_shortage"
        assert result["error"].startswith("소스 글이 부족합니다: 0개")
    finally:
        session.close()


def test_targeted_backfill_restores_writing_source_count(migration_env):
    _run_targeted_backfill(migration_env)

    rows = verify.collect_row_counts(
        migration_env["sqlite_engine"],
        migration_env["pg_engine"],
        ["writing_sources", "task_schedules", "task_schedule_runs"],
    )
    row_map = {row["table"]: row for row in rows}
    assert row_map["writing_sources"]["sqlite_count"] == 3
    assert row_map["writing_sources"]["pg_count"] == 3
    assert row_map["writing_sources"]["red_flag"] is False


def test_collect_history_recovers_diagnostic_signal_after_backfill(migration_env):
    _run_targeted_backfill(migration_env)

    session = migration_env["pg_sessionmaker"]()
    try:
        schedule = _seed_pg_schedule(session)
        run = TaskScheduleRun(schedule_id=schedule.id, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)

        worker = WritingWorker(session, project_root=REPO_ROOT)
        with patch.object(WritingWorker, "_queue_mix_writing", return_value=True), \
             patch.object(WritingWorker, "_queue_random_writing", return_value=True), \
             patch.object(WritingWorker, "_queue_keyword_writing", return_value=True):
            result = worker.run(schedule, run)
        session.refresh(run)

        service = CollectService(session)
        items, total, _stats = service.get_crawl_history(
            source_type="writing",
            status=None,
            period="month",
            page=1,
            limit=20,
        )
        found = next((item for item in items if item.id == run.id), None)

        assert total >= 1
        assert result.get("error") is None
        assert run.status == TaskScheduleRun.STATUS_COMPLETED
        assert found is not None
        assert found.status == "completed"
        assert found.stop_reason == "completed"
        assert found.error_message is None
    finally:
        session.close()


def test_verify_writing_gap_returns_clean_after_backfill(migration_env):
    _run_targeted_backfill(migration_env)

    rows = verify.collect_row_counts(
        migration_env["sqlite_engine"],
        migration_env["pg_engine"],
        ["writing_sources", "task_schedules", "task_schedule_runs"],
    )

    assert all(row["mismatch"] is False for row in rows)
    assert all(row["red_flag"] is False for row in rows)
