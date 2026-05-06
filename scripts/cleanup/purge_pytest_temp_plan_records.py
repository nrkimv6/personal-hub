"""Dry-run/confirm purge for pytest-created PlanRecord rows.

The default mode is read-only. Confirmed deletion is intentionally guarded so
production-like URLs need an explicit allow flag in addition to --confirm.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Keep --json stdout machine-readable even if imported app modules configure
# console logging during startup.
if "--json" in sys.argv:
    logging.disable(logging.CRITICAL)

from app.core.config import settings  # noqa: E402
from app.models.plan_record import PlanEvent, PlanRecord  # noqa: E402
from app.modules.claude_worker.models.llm_request import LLMRequest  # noqa: E402
from app.modules.dev_runner.services.plan_record_service import _is_temp_pytest_path  # noqa: E402


def _create_engine(database_url: str):
    from sqlalchemy import create_engine

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def _candidate_prefilter(session):
    return session.query(PlanRecord).filter(
        or_(
            PlanRecord.file_path.ilike(r"%\Temp\pytest-%"),
            PlanRecord.file_path.ilike(r"%\Temp\pytest-of-%"),
            PlanRecord.file_path.ilike("%/tmp/pytest-%"),
            PlanRecord.file_path.ilike("%/tmp/pytest-of-%"),
            PlanRecord.file_path.ilike("%/pytest-%"),
            PlanRecord.file_path.ilike("%/pytest-of-%"),
        )
    )


def find_candidates(session, limit: int | None = None) -> list[PlanRecord]:
    rows = _candidate_prefilter(session).order_by(PlanRecord.id.asc()).all()
    candidates = [row for row in rows if _is_temp_pytest_path(row.file_path)]
    if limit is not None:
        return candidates[: max(0, limit)]
    return candidates


def build_summary(session, candidates: list[PlanRecord], *, dry_run: bool) -> dict[str, Any]:
    ids = [row.id for row in candidates]
    hashes = [row.filename_hash for row in candidates]
    events_count = 0
    llm_count = 0
    if ids:
        events_count = session.query(PlanEvent).filter(PlanEvent.plan_record_id.in_(ids)).count()
    if hashes:
        llm_count = session.query(LLMRequest).filter(LLMRequest.caller_id.in_(hashes)).count()
    return {
        "dry_run": dry_run,
        "candidate_count": len(candidates),
        "plan_event_count": events_count,
        "llm_request_count": llm_count,
        "examples": [
            {
                "id": row.id,
                "filename_hash": row.filename_hash,
                "file_path": row.file_path,
                "status": row.status,
            }
            for row in candidates[:10]
        ],
    }


def purge_candidates(session, candidates: list[PlanRecord]) -> dict[str, int]:
    ids = [row.id for row in candidates]
    hashes = [row.filename_hash for row in candidates]
    now = datetime.now()
    deleted_events = 0
    soft_deleted_llm_requests = 0
    deleted_records = 0
    if ids:
        deleted_events = (
            session.query(PlanEvent)
            .filter(PlanEvent.plan_record_id.in_(ids))
            .delete(synchronize_session=False)
        )
    if hashes:
        requests = session.query(LLMRequest).filter(LLMRequest.caller_id.in_(hashes)).all()
        for request in requests:
            if request.deleted_at is None:
                request.deleted_at = now
                soft_deleted_llm_requests += 1
    if ids:
        deleted_records = (
            session.query(PlanRecord)
            .filter(PlanRecord.id.in_(ids))
            .delete(synchronize_session=False)
        )
    return {
        "plan_events_deleted": deleted_events,
        "llm_requests_soft_deleted": soft_deleted_llm_requests,
        "plan_records_deleted": deleted_records,
    }


def is_production_like_url(database_url: str) -> bool:
    lowered = database_url.lower()
    if lowered.startswith("postgresql://") or lowered.startswith("postgresql+"):
        return True
    if lowered.startswith("sqlite"):
        return not any(token in lowered for token in ("test", "tmp", "pytest", ":memory:"))
    return True


def run(
    *,
    database_url: str,
    confirm: bool,
    allow_production: bool,
    limit: int | None,
) -> dict[str, Any]:
    if confirm and is_production_like_url(database_url) and not allow_production:
        return {
            "dry_run": False,
            "error": "PRODUCTION_CONFIRM_REQUIRES_ALLOW_PRODUCTION",
            "candidate_count": 0,
        }

    engine = _create_engine(database_url)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    try:
        candidates = find_candidates(session, limit=limit)
        summary = build_summary(session, candidates, dry_run=not confirm)
        if not confirm:
            session.rollback()
            return summary
        mutation_summary = purge_candidates(session, candidates)
        session.commit()
        return {**summary, "dry_run": False, **mutation_summary}
    except Exception as exc:
        session.rollback()
        return {"dry_run": not confirm, "error": str(exc), "candidate_count": 0}
    finally:
        session.close()
        engine.dispose()


def _print_text(summary: dict[str, Any]) -> None:
    if summary.get("error"):
        print(f"error: {summary['error']}")
        return
    mode = "dry-run" if summary.get("dry_run") else "confirm"
    print(f"mode: {mode}")
    print(f"candidate_count: {summary.get('candidate_count', 0)}")
    print(f"plan_event_count: {summary.get('plan_event_count', 0)}")
    print(f"llm_request_count: {summary.get('llm_request_count', 0)}")
    if not summary.get("dry_run"):
        print(f"plan_events_deleted: {summary.get('plan_events_deleted', 0)}")
        print(f"llm_requests_soft_deleted: {summary.get('llm_requests_soft_deleted', 0)}")
        print(f"plan_records_deleted: {summary.get('plan_records_deleted', 0)}")
    for item in summary.get("examples", []):
        print(f"example: #{item['id']} {item['file_path']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=settings.DATABASE_URL)
    parser.add_argument("--confirm", action="store_true", help="Apply deletion/soft-delete changes.")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Required with --confirm for production-like database URLs.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        database_url=args.database_url,
        confirm=args.confirm,
        allow_production=args.allow_production,
        limit=args.limit,
    )
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        _print_text(summary)
    return 2 if summary.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
