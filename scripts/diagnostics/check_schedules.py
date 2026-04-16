#!/usr/bin/env python3
"""현재 운영 DB 기준 스케줄 상태 확인 스크립트."""
import json
import sys
from pathlib import Path

from sqlalchemy import inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal


def _print_header(title: str) -> None:
    print("=" * 80)
    print(title)
    print("=" * 80)


def _load_config(raw_value):
    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return {}
    return {}


def main() -> int:
    db = SessionLocal()

    try:
        inspector = inspect(db.get_bind())
        tables = set(inspector.get_table_names())

        if "task_schedules" not in tables:
            print("task_schedules 테이블이 없습니다.")
            return 1

        _print_header("task_schedules schema")
        for column in inspector.get_columns("task_schedules"):
            print(
                f"{column['name']}: {column['type']} "
                f"(nullable={column.get('nullable')}, default={column.get('default')})"
            )
        print()

        active_rows = db.execute(
            text(
                """
                SELECT id, name, target_type, enabled, last_run_at, next_run_at, target_config
                FROM task_schedules
                WHERE enabled = true
                ORDER BY CASE WHEN next_run_at IS NULL THEN 1 ELSE 0 END, next_run_at, id
                LIMIT 50
                """
            )
        ).mappings().all()

        _print_header("Active Schedules")
        if not active_rows:
            print("(활성 스케줄 없음)")
        for row in active_rows:
            config = _load_config(row["target_config"])
            print(f"ID: {row['id']}, Name: {row['name']}, Type: {row['target_type']}")
            print(f"  enabled: {row['enabled']}")
            print(f"  Last: {row['last_run_at']}")
            print(f"  Next: {row['next_run_at']}")
            print(f"  target_config keys: {sorted(config.keys()) if config else []}")
            print()

        _print_header("Recent Schedule Runs (last 20)")
        if "task_schedule_runs" not in tables:
            print("task_schedule_runs 테이블이 없습니다.")
            return 0

        run_rows = db.execute(
            text(
                """
                SELECT r.id, s.name, s.target_type, r.status, r.started_at, r.finished_at, r.stop_reason
                FROM task_schedule_runs r
                JOIN task_schedules s ON r.schedule_id = s.id
                ORDER BY r.id DESC
                LIMIT 20
                """
            )
        ).mappings().all()

        if not run_rows:
            print("(최근 실행 이력 없음)")
            return 0

        for row in run_rows:
            print(f"Run #{row['id']}: {row['name']} ({row['target_type']})")
            print(
                f"  Status: {row['status']}, "
                f"Started: {row['started_at']}, Finished: {row['finished_at']}"
            )
            print(f"  Reason: {row['stop_reason']}")
            print()

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
