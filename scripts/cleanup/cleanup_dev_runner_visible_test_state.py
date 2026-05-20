"""Dry-run/apply cleanup for synthetic dev-runner state rows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models.dev_runner_state import DevRunnerMergeRequest, DevRunnerState  # noqa: E402
from app.modules.dev_runner.services.visibility import is_visible_runner_evidence  # noqa: E402


def _synthetic_rows(session) -> list[DevRunnerState]:
    rows = session.query(DevRunnerState).all()
    result: list[DevRunnerState] = []
    for row in rows:
        meta = row.metadata_json or {}
        if meta.get("trigger") not in {"user", "user:all"}:
            continue
        if is_visible_runner_evidence(
            runner_id=row.runner_id,
            trigger=meta.get("trigger"),
            plan_file=row.plan_file,
            worktree_path=row.worktree_path,
            branch=row.branch,
            redis_missing=True,
            status=row.status,
            test_source=meta.get("test_source"),
        ):
            continue
        result.append(row)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="delete exact synthetic candidates")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        rows = _synthetic_rows(session)
        payload = {
            "apply": args.apply,
            "count": len(rows),
            "runner_ids": [row.runner_id for row in rows],
            "items": [
                {
                    "runner_id": row.runner_id,
                    "plan_file": row.plan_file,
                    "status": row.status,
                    "trigger": (row.metadata_json or {}).get("trigger"),
                    "branch": row.branch,
                    "worktree_path": row.worktree_path,
                }
                for row in rows
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if args.apply and rows:
            runner_ids = [row.runner_id for row in rows]
            session.query(DevRunnerMergeRequest).filter(DevRunnerMergeRequest.runner_id.in_(runner_ids)).delete(
                synchronize_session=False
            )
            session.query(DevRunnerState).filter(DevRunnerState.runner_id.in_(runner_ids)).delete(
                synchronize_session=False
            )
            session.commit()
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
