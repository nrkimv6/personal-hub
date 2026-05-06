"""Backfill plan_records.file_delete_after for processed archive records.

Usage:
  python scripts/migrations/backfill_plan_record_file_delete_after.py --dry-run
  python scripts/migrations/backfill_plan_record_file_delete_after.py --apply
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def run(apply: bool = False) -> dict:
    from app.database import SessionLocal
    from app.models.plan_record import PlanRecord
    from app.modules.dev_runner.services.plan_record_service import _exclude_temp_pytest_records

    with SessionLocal() as db:
        query = db.query(PlanRecord).filter(
            PlanRecord.llm_processed_at.isnot(None),
            PlanRecord.raw_content.isnot(None),
            PlanRecord.file_removed_at.is_(None),
            PlanRecord.file_delete_after.is_(None),
        )
        query = _exclude_temp_pytest_records(query)
        targets = query.all()
        if apply:
            for record in targets:
                record.file_delete_after = record.llm_processed_at + timedelta(days=7)
            db.commit()
        return {"matched": len(targets), "updated": len(targets) if apply else 0, "dry_run": not apply}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True)
    group.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args()
    print(run(apply=args.apply))
