"""auto_dev_runner 스케줄 seed (insert-if-missing).

실행:
    python scripts/migrations/seed_auto_dev_runner_schedule.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import SessionLocal
from app.models import TaskSchedule


def seed():
    db = SessionLocal()
    try:
        existing = (
            db.query(TaskSchedule)
            .filter(TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_AUTO_DEV_RUNNER)
            .first()
        )
        if existing:
            print(f"[seed] auto_dev_runner schedule already exists: id={existing.id}")
            return

        import json
        schedule = TaskSchedule(
            name="auto_dev_runner_nightly",
            display_name="야간 자동 plan 실행 (02:00)",
            target_type=TaskSchedule.TARGET_TYPE_AUTO_DEV_RUNNER,
            schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
            schedule_value=json.dumps({"cron": "0 2 * * *"}),
            enabled=True,
            target_config=None,
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        print(f"[seed] created auto_dev_runner schedule: id={schedule.id}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
