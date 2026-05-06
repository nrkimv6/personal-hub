from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.biz_item import BizItem
from app.models.business import Business
from app.models.monitor_schedule import MonitorSchedule


@pytest.fixture
def booking_session_factory(test_db_session):
    test_db_session.execute(text("""
        CREATE TABLE IF NOT EXISTS booking_settings (
            id INTEGER PRIMARY KEY,
            dry_run_mode BOOLEAN DEFAULT 0,
            max_parallel_tabs INTEGER DEFAULT 3
        )
    """))
    test_db_session.commit()
    return sessionmaker(bind=test_db_session.get_bind())


@pytest.fixture
def seeded_booking_settings(test_db_session):
    test_db_session.execute(text("""
        CREATE TABLE IF NOT EXISTS booking_settings (
            id INTEGER PRIMARY KEY,
            dry_run_mode BOOLEAN DEFAULT 0,
            max_parallel_tabs INTEGER DEFAULT 3
        )
    """))
    test_db_session.execute(text("DELETE FROM booking_settings"))
    test_db_session.execute(text("""
        INSERT INTO booking_settings (id, dry_run_mode, max_parallel_tabs)
        VALUES (1, 1, 6)
    """))
    test_db_session.commit()
    return test_db_session


@pytest.fixture
def seeded_booking_schedule(test_db_session):
    unique_id = uuid4().hex[:8]
    business = Business(
        business_id=f"named_access_biz_{unique_id}",
        name=f"Named Access Biz {unique_id}",
        business_type_id=13,
        service_type="naver",
    )
    test_db_session.add(business)
    test_db_session.flush()

    item = BizItem(
        business_id=business.id,
        biz_item_id=f"named_item_{unique_id}",
        name=f"Named Item {unique_id}",
    )
    test_db_session.add(item)
    test_db_session.flush()

    schedule = MonitorSchedule(
        biz_item_id=item.id,
        date="2026-04-24",
        is_enabled=True,
        booking_count=4,
        last_booking_time=datetime(2026, 4, 24, 9, 30, 0),
    )
    test_db_session.add(schedule)
    test_db_session.commit()
    test_db_session.refresh(schedule)
    return schedule


def test_get_booking_settings_reads_named_mapping_fields(
    booking_session_factory,
    seeded_booking_settings,
):
    from app.modules.naver_booking.routes.booking import get_booking_settings_from_db

    with patch("app.modules.naver_booking.routes.booking.SessionLocal", booking_session_factory):
        result = get_booking_settings_from_db()

    assert result == {"dry_run_mode": True, "max_parallel_tabs": 6}


@pytest.mark.asyncio
async def test_get_booking_stats_reads_named_mapping_fields(
    booking_session_factory,
    seeded_booking_schedule,
):
    from app.modules.naver_booking.routes.booking import get_booking_stats_by_schedule

    with patch("app.modules.naver_booking.routes.booking.SessionLocal", booking_session_factory):
        result = await get_booking_stats_by_schedule(seeded_booking_schedule.id)

    assert result.schedule_id == seeded_booking_schedule.id
    assert result.booking_count == 4
    assert result.last_booked_at == datetime(2026, 4, 24, 9, 30, 0)


@pytest.mark.asyncio
async def test_booking_named_access_regression_shape_preserved(
    booking_session_factory,
    seeded_booking_settings,
    seeded_booking_schedule,
):
    from app.modules.naver_booking.routes.booking import (
        get_booking_settings_from_db,
        get_booking_stats_by_schedule,
    )

    with patch("app.modules.naver_booking.routes.booking.SessionLocal", booking_session_factory):
        settings_result = get_booking_settings_from_db()
        stats_result = await get_booking_stats_by_schedule(seeded_booking_schedule.id)

    assert sorted(settings_result.keys()) == ["dry_run_mode", "max_parallel_tabs"]
    assert set(stats_result.model_dump().keys()) == {
        "schedule_id",
        "booking_count",
        "last_booked_at",
    }
