"""
SQLite -> PostgreSQL writing 계열 row-count 검증 스크립트.

실행:
    python scripts/migrations/verify_writing_migration.py
    python scripts/migrations/verify_writing_migration.py --sqlite-path D:/work/project/tools/monitor-page/data/monitor.db
    python scripts/migrations/verify_writing_migration.py --tables writing_sources,generated_writings
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from sqlalchemy import create_engine, inspect, text

MIGRATIONS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MIGRATIONS_DIR))

from migrate_sqlite_to_pg import (
    WRITING_TABLES,
    _DEFAULT_SQLITE_PATH,
    get_pg_url,
    parse_selected_tables_arg,
)
from app.models.task_schedule import TaskSchedule

WRITING_TARGET_TYPES = (
    TaskSchedule.TARGET_TYPE_WRITING_TASK,
    TaskSchedule.TARGET_TYPE_WRITING_SOURCE_COLLECT,
    TaskSchedule.TARGET_TYPE_KEYWORD_ANALYSIS,
    TaskSchedule.TARGET_TYPE_TOPIC_EXTRACT,
)
WRITING_TARGET_TYPES_SQL = ", ".join(f"'{value}'" for value in WRITING_TARGET_TYPES)


def table_exists(engine, table_name: str) -> bool:
    return table_name in inspect(engine).get_table_names()


def build_count_query(table_name: str) -> tuple[str, dict]:
    if table_name == "task_schedules":
        return (
            f"SELECT COUNT(*) FROM task_schedules WHERE target_type IN ({WRITING_TARGET_TYPES_SQL})",
            {},
        )
    if table_name == "task_schedule_runs":
        return (
            f"""
            SELECT COUNT(*)
            FROM task_schedule_runs runs
            JOIN task_schedules schedules ON schedules.id = runs.schedule_id
            WHERE schedules.target_type IN ({WRITING_TARGET_TYPES_SQL})
            """,
            {},
        )
    return (f"SELECT COUNT(*) FROM {table_name}", {})


def fetch_row_count(engine, table_name: str) -> Optional[int]:
    if not table_exists(engine, table_name):
        return None

    sql, params = build_count_query(table_name)
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def collect_row_counts(
    sqlite_engine,
    pg_engine,
    tables: Optional[Sequence[str]] = None,
) -> list[dict[str, Optional[int] | str | bool]]:
    target_tables = list(tables or WRITING_TABLES)
    rows: list[dict[str, Optional[int] | str | bool]] = []

    for table_name in target_tables:
        sqlite_count = fetch_row_count(sqlite_engine, table_name)
        pg_count = fetch_row_count(pg_engine, table_name)
        mismatch = sqlite_count != pg_count
        red_flag = bool((sqlite_count or 0) > 0 and (pg_count or 0) == 0)
        rows.append(
            {
                "table": table_name,
                "sqlite_count": sqlite_count,
                "pg_count": pg_count,
                "mismatch": mismatch,
                "red_flag": red_flag,
            }
        )
    return rows


def print_summary(rows: Sequence[dict[str, Optional[int] | str | bool]]) -> None:
    print("=" * 60)
    print("Writing migration row-count audit")
    print("=" * 60)

    for row in rows:
        status = "OK"
        if row["red_flag"]:
            status = "RED_FLAG"
        elif row["mismatch"]:
            status = "MISMATCH"
        print(
            f"{status:10s} {row['table']}: "
            f"SQLite={row['sqlite_count']} | PG={row['pg_count']}"
        )

    red_flags = [row for row in rows if row["red_flag"]]
    if red_flags:
        print("\n[red flag]")
        for row in red_flags:
            print(
                f"  - {row['table']}: SQLite에는 데이터가 있지만 PG는 0건입니다. "
                "collect/history 글쓰기 실패와 직접 연결될 수 있습니다."
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="writing 계열 SQLite↔PG row-count 검증")
    parser.add_argument(
        "--sqlite-path",
        type=str,
        default=None,
        help=f"SQLite DB 파일 경로 (기본값: {_DEFAULT_SQLITE_PATH})",
    )
    parser.add_argument(
        "--tables",
        type=str,
        default=None,
        help="쉼표로 구분한 writing 검증 테이블 목록",
    )
    args = parser.parse_args()

    sqlite_path = (Path(args.sqlite_path) if args.sqlite_path else _DEFAULT_SQLITE_PATH).resolve()
    if not sqlite_path.exists():
        print(f"ERROR: SQLite DB 파일을 찾을 수 없습니다: {sqlite_path}")
        return 1

    selected_tables = parse_selected_tables_arg(args.tables)
    sqlite_engine = create_engine(f"sqlite:///{sqlite_path.as_posix()}")
    pg_engine = create_engine(get_pg_url(), pool_pre_ping=True)

    try:
        rows = collect_row_counts(sqlite_engine, pg_engine, selected_tables)
        print_summary(rows)
    finally:
        sqlite_engine.dispose()
        pg_engine.dispose()

    has_mismatch = any(bool(row["mismatch"]) for row in rows)
    return 1 if has_mismatch else 0


if __name__ == "__main__":
    sys.exit(main())
