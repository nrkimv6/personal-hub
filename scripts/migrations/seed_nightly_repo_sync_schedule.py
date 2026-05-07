"""nightly_repo_sync schedule seed (insert-if-missing).

Run:
    python scripts/migrations/seed_nightly_repo_sync_schedule.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import SessionLocal
from app.models import TaskSchedule


def seed() -> None:
    db = SessionLocal()
    try:
        existing = db.query(TaskSchedule).filter_by(name="nightly_repo_sync_daily").first()
        if existing:
            print(f"[seed] nightly_repo_sync schedule already exists: id={existing.id}")
            return
        schedule = TaskSchedule(
            name="nightly_repo_sync_daily",
            display_name="Nightly Main/Plans Sync",
            target_type=TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC,
            target_config=json.dumps(
                {
                    "repo_root": r"D:\work\project\tools\monitor-page",
                    "allow_mutation": True,
                },
                ensure_ascii=False,
            ),
            schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
            schedule_value="0 3 * * *",
            enabled=True,
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        print(f"[seed] created nightly_repo_sync schedule: id={schedule.id}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
