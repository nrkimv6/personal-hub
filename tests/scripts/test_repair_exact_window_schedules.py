"""Exact-window repair script contract tests."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import TaskSchedule
from scripts.fixes.repair_exact_window_schedules import (
    build_repaired_schedule_value,
    exact_windows_to_ranges,
    repair_exact_window_schedules,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    TaskSchedule.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_exact_windows_to_ranges_R_schedule_one_windows_use_next_slot_or_one_hour():
    windows = [
        {"start": "22:00", "end": "22:00"},
        {"start": "07:00", "end": "07:00"},
        {"start": "09:20", "end": "09:20"},
        {"start": "10:00", "end": "10:00"},
        {"start": "12:00", "end": "12:00"},
        {"start": "14:00", "end": "14:00"},
        {"start": "15:00", "end": "15:00"},
        {"start": "17:00", "end": "17:00"},
    ]

    assert exact_windows_to_ranges(windows) == [
        {"start": "07:00", "end": "08:00"},
        {"start": "09:20", "end": "10:00"},
        {"start": "10:00", "end": "11:00"},
        {"start": "12:00", "end": "13:00"},
        {"start": "14:00", "end": "15:00"},
        {"start": "15:00", "end": "16:00"},
        {"start": "17:00", "end": "18:00"},
        {"start": "22:00", "end": "23:00"},
    ]


def test_build_repaired_schedule_value_B_midnight_wraps_last_one_hour_window():
    repaired = build_repaired_schedule_value(
        {
            "daily_runs": 1,
            "time_windows": [{"start": "23:30", "end": "23:30"}],
        }
    )

    assert repaired["time_windows"] == [{"start": "23:30", "end": "00:30"}]


def test_build_repaired_schedule_value_R_preserves_existing_range_windows():
    repaired = build_repaired_schedule_value(
        {
            "daily_runs": 2,
            "time_windows": [
                {"start": "14:00", "end": "16:00"},
                {"start": "09:00", "end": "09:00"},
            ],
        }
    )

    assert repaired["time_windows"] == [
        {"start": "09:00", "end": "10:00"},
        {"start": "14:00", "end": "16:00"},
    ]


def test_apply_E_requires_explicit_ids():
    with pytest.raises(ValueError, match="--ids"):
        repair_exact_window_schedules(apply=True, session=object())


def test_dry_run_does_not_mutate_exact_schedule(db_session):
    schedule = TaskSchedule(
        name="legacy_exact",
        target_type=TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
        enabled=True,
        schedule_value=json.dumps(
            {
                "daily_runs": 1,
                "time_windows": [{"start": "09:00", "end": "09:00"}],
            }
        ),
    )
    db_session.add(schedule)
    db_session.commit()
    db_session.refresh(schedule)

    result = repair_exact_window_schedules(session=db_session)
    db_session.refresh(schedule)

    assert result["dry_run"] is True
    assert result["candidate_count"] == 1
    assert result["repaired_count"] == 0
    assert json.loads(schedule.schedule_value)["time_windows"] == [
        {"start": "09:00", "end": "09:00"}
    ]
