"""Reindex explicit plan-body relations for PlanRecord rows."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if "--json" in sys.argv:
    logging.disable(logging.CRITICAL)

from app.core.config import settings  # noqa: E402
from app.models.plan_archive_execution import PlanArchiveExecutionAttempt, PlanArchiveExecutionJob  # noqa: E402,F401
from app.models.plan_record import PlanRecord  # noqa: E402
from app.modules.claude_worker.models.llm_request import LLMRequest  # noqa: E402,F401
from app.modules.dev_runner.services.plan_archive_relation_service import (  # noqa: E402
    PLAN_BODY_RELATION_TYPES,
    PlanArchiveRelationService,
)


def _create_engine(database_url: str):
    from sqlalchemy import create_engine

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def _query_records(session, *, record_id: int | None, limit: int | None):
    query = session.query(PlanRecord).order_by(PlanRecord.id.asc())
    if record_id:
        query = query.filter(PlanRecord.id == record_id)
    else:
        query = query.filter((PlanRecord.raw_content.isnot(None)) | (PlanRecord.file_path.isnot(None)))
    if limit:
        query = query.limit(limit)
    return query.all()


def run(
    *,
    database_url: str | None = None,
    apply: bool = False,
    record_id: int | None = None,
    relation_type: str | None = None,
    limit: int | None = None,
    include_details: bool = False,
) -> dict[str, Any]:
    relation_types = None
    if relation_type:
        relation_types = [relation_type]
    database_url = database_url or settings.DATABASE_URL
    engine = _create_engine(database_url)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    try:
        records = _query_records(session, record_id=record_id, limit=limit)
        service = PlanArchiveRelationService(session)
        details = []
        totals = {
            "dry_run": not apply,
            "record_count": len(records),
            "created": 0,
            "updated": 0,
            "stale_deleted": 0,
            "skipped": 0,
            "unresolved_targets": 0,
            "relation_types": sorted(relation_types or PLAN_BODY_RELATION_TYPES),
        }
        if include_details:
            totals["details"] = details
        for record in records:
            result = service.refresh_relations_for_record(
                record.id,
                dry_run=not apply,
                relation_types=relation_types,
            )
            data = result.to_dict()
            details.append(data)
            totals["created"] += data["created"]
            totals["updated"] += data["updated"]
            totals["stale_deleted"] += data["stale_deleted"]
            totals["skipped"] += len(data["skipped"])
            totals["unresolved_targets"] += len(data["unresolved_targets"])
        if apply:
            session.commit()
        else:
            session.rollback()
        return totals
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--record-id", type=int, default=None)
    parser.add_argument("--relation-type", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--details", action="store_true", help="Include per-record refresh details in JSON output")
    args = parser.parse_args(argv)
    previous_logging_disable = logging.root.manager.disable
    if args.json:
        logging.disable(logging.CRITICAL)

    try:
        summary = run(
            database_url=args.database_url,
            apply=args.apply,
            record_id=args.record_id,
            relation_type=args.relation_type,
            limit=args.limit,
            include_details=args.details,
        )
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, default=str))
        else:
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    finally:
        if args.json:
            logging.disable(previous_logging_disable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
