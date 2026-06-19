"""
CLI entrypoint for BigQuery event export.

Usage examples:
    # Dry-run (default) — no real inserts
    python scripts/gcp/export_events.py --since 2026-06-01 --until 2026-06-07

    # Live insert (requires ENABLE_BIGQUERY_EXPORT=true)
    python scripts/gcp/export_events.py --since 2026-06-01 --until 2026-06-07 --apply
"""

import argparse
import sys
from datetime import datetime

# Ensure project root is on sys.path when run directly
import os
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Export personal-hub events to BigQuery personal_hub_events table."
    )
    parser.add_argument(
        "--since",
        required=True,
        help="Start date/datetime (ISO format, e.g. 2026-06-01 or 2026-06-01T00:00:00)",
    )
    parser.add_argument(
        "--until",
        required=True,
        help="End date/datetime (ISO format, e.g. 2026-06-07 or 2026-06-07T23:59:59)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Perform real BigQuery insert (default: dry-run only)",
    )
    parser.add_argument(
        "--table-id",
        default="personal_hub.dataset.personal_hub_events",
        help="Fully-qualified BigQuery table ID",
    )
    return parser.parse_args(argv)


def _parse_dt(s: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"날짜 형식을 파싱할 수 없습니다: {s!r}. ISO 형식(2026-06-01)을 사용하세요.")


def main(argv=None):
    args = parse_args(argv)
    since = _parse_dt(args.since)
    until = _parse_dt(args.until)
    dry_run = not args.apply

    from app.db.session import SessionLocal
    from app.modules.bigquery_export.export import export_events

    db = SessionLocal()
    try:
        summary = export_events(
            db_session=db,
            since=since,
            until=until,
            dry_run=dry_run,
            table_id=args.table_id,
        )
    finally:
        db.close()

    mode = "dry-run" if dry_run else "live"
    print(f"=== BigQuery Export Summary ({mode}) ===")
    print(f"  since        : {since.isoformat()}")
    print(f"  until        : {until.isoformat()}")
    print(f"  total_read   : {summary.total_read}")
    print(f"  total_valid  : {summary.total_valid}")
    print(f"  total_inserted: {summary.total_inserted}")
    print(f"  total_skipped: {summary.total_skipped}")
    if summary.errors:
        print(f"  errors ({len(summary.errors)}):")
        for err in summary.errors[:10]:
            print(f"    - {err}")
        if len(summary.errors) > 10:
            print(f"    ... and {len(summary.errors) - 10} more")

    return summary


if __name__ == "__main__":
    main()
