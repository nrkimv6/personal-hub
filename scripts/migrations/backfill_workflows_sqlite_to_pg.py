"""
SQLite -> PostgreSQL workflows backfill script.

Usage:
    python scripts/migrations/backfill_workflows_sqlite_to_pg.py --dry-run
    python scripts/migrations/backfill_workflows_sqlite_to_pg.py --apply
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_data_root() -> Path:
    """worktree 실행 시에도 실제 repo 루트의 data/monitor.db를 찾는다."""
    for candidate in (PROJECT_ROOT, PROJECT_ROOT.parents[1]):
        if (candidate / "data" / "monitor.db").exists():
            return candidate
    return PROJECT_ROOT


DATA_ROOT = _resolve_data_root()
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.models.workflow import Workflow as WorkflowModel

logger = logging.getLogger("backfill_workflows_sqlite_to_pg")

DEFAULT_SQLITE_PATH = DATA_ROOT / "data" / "monitor.db"
_WORKFLOW_TABLE = WorkflowModel.__table__
_WORKFLOW_COLUMNS = [column.name for column in _WORKFLOW_TABLE.columns]
_TIMESTAMP_COLUMNS = {"created_at", "started_at", "merged_at", "finished_at"}


def _normalize_db_url(db_source: str) -> str:
    raw = str(db_source).strip()
    if "://" in raw:
        return raw
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return f"sqlite:///{path.resolve().as_posix()}"


def _engine_kwargs(db_url: str) -> dict:
    if db_url.startswith("sqlite"):
        kwargs = {
            "pool_pre_ping": True,
            "connect_args": {"check_same_thread": False},
        }
        if db_url.endswith(":memory:"):
            kwargs["poolclass"] = StaticPool
        return kwargs
    return {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_timeout": 10,
        "pool_size": 5,
        "max_overflow": 10,
        "connect_args": {"connect_timeout": 5},
    }


def _normalize_scalar(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return ""
        for parser in (datetime.fromisoformat, date.fromisoformat):
            try:
                parsed = parser(candidate)
            except ValueError:
                continue
            if isinstance(parsed, datetime):
                return parsed.isoformat(sep=" ", timespec="microseconds")
            return parsed.isoformat()
        return candidate
    return value


def _normalize_row(row: Mapping) -> tuple[tuple[str, object], ...]:
    return tuple((column, _normalize_scalar(row.get(column))) for column in _WORKFLOW_COLUMNS)


def _diff_row(src: Mapping, dst: Mapping) -> dict[str, tuple[object, object]]:
    diff: dict[str, tuple[object, object]] = {}
    for column in _WORKFLOW_COLUMNS:
        src_value = _normalize_scalar(src.get(column))
        dst_value = _normalize_scalar(dst.get(column))
        if src_value != dst_value:
            diff[column] = (src_value, dst_value)
    return diff


def _coerce_row_for_insert(row: Mapping) -> dict:
    payload = dict(row)
    for column in _TIMESTAMP_COLUMNS:
        value = payload.get(column)
        if isinstance(value, str) and value.strip():
            try:
                payload[column] = datetime.fromisoformat(value.strip())
            except ValueError:
                payload[column] = value
    return payload


def _make_sqlite_engine(sqlite_path: Path):
    return create_engine(
        f"sqlite:///{sqlite_path.resolve().as_posix()}",
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )


def _make_pg_engine(pg_url: str):
    return create_engine(pg_url, **_engine_kwargs(pg_url))


def _load_rows(engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM workflows ORDER BY id")).mappings().all()
    return [dict(row) for row in rows]


def _sync_workflow_sequence(conn) -> None:
    conn.execute(
        text(
            """
            SELECT setval(
                pg_get_serial_sequence('workflows', 'id'),
                COALESCE((SELECT MAX(id) FROM workflows), 1),
                (SELECT MAX(id) FROM workflows) IS NOT NULL
            )
            """
        )
    )


def run(
    *,
    sqlite_path: Path = DEFAULT_SQLITE_PATH,
    pg_url: str | None = None,
    apply: bool = False,
) -> dict[str, object]:
    """Backfill SQLite workflows into PostgreSQL."""
    if pg_url is None:
        pg_url = settings.DATABASE_URL

    if not str(pg_url).startswith("postgresql"):
        raise ValueError(f"DATABASE_URL must point to PostgreSQL: {pg_url}")
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {sqlite_path}")

    sqlite_engine = _make_sqlite_engine(sqlite_path)
    pg_engine = _make_pg_engine(pg_url)

    try:
        sqlite_rows = _load_rows(sqlite_engine)
        pg_rows = _load_rows(pg_engine)
        pg_by_id = {row["id"]: row for row in pg_rows}

        to_insert: list[dict] = []
        skipped = 0

        for row in sqlite_rows:
            existing = pg_by_id.get(row["id"])
            if existing is None:
                to_insert.append(_coerce_row_for_insert(row))
                continue

            if _normalize_row(existing) == _normalize_row(row):
                skipped += 1
                continue

            diff = _diff_row(row, existing)
            logger.error("workflow conflict detected: id=%s diff=%s", row["id"], diff)
            return {
                "applied": False,
                "inserted": 0,
                "skipped": skipped,
                "conflicts": 1,
                "conflict_id": row["id"],
                "diff": diff,
            }

        if not apply:
            logger.info(
                "[DRY-RUN] sqlite=%s pg=%s existing=%s insert=%s skipped=%s",
                len(sqlite_rows),
                len(pg_rows),
                len(sqlite_rows) - len(to_insert),
                len(to_insert),
                skipped,
            )
            return {
                "applied": False,
                "inserted": 0,
                "skipped": skipped,
                "conflicts": 0,
                "planned_inserted": len(to_insert),
            }

        inserted = 0
        if to_insert:
            columns = ", ".join(_WORKFLOW_COLUMNS)
            params = ", ".join(f":{column}" for column in _WORKFLOW_COLUMNS)
            insert_stmt = text(f"INSERT INTO workflows ({columns}) VALUES ({params})")
            with pg_engine.begin() as conn:
                conn.execute(insert_stmt, to_insert)
                inserted = len(to_insert)
                _sync_workflow_sequence(conn)
        else:
            with pg_engine.begin() as conn:
                _sync_workflow_sequence(conn)

        logger.info(
            "workflow backfill complete: inserted=%s skipped=%s conflicts=0",
            inserted,
            skipped,
        )
        return {
            "applied": True,
            "inserted": inserted,
            "skipped": skipped,
            "conflicts": 0,
        }
    finally:
        sqlite_engine.dispose()
        pg_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill SQLite workflows into PostgreSQL")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="Preview only")
    group.add_argument("--apply", action="store_true", help="Apply inserts")
    parser.add_argument(
        "--sqlite-path",
        default=str(DEFAULT_SQLITE_PATH),
        help="SQLite DB path (default: data/monitor.db)",
    )
    parser.add_argument(
        "--pg-url",
        default=None,
        help="PostgreSQL URL override (default: app settings DATABASE_URL)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    result = run(
        sqlite_path=Path(args.sqlite_path),
        pg_url=args.pg_url,
        apply=args.apply,
    )
    if result.get("conflicts"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
