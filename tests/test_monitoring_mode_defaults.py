"""
monitoring_mode anonymous 기본값 / backfill 회귀 테스트
"""
from uuid import uuid4

from sqlalchemy import text

from app.core.database import repair_monitor_schedule_monitoring_mode
from app.models.business import Business
from app.models.biz_item import BizItem
from app.models.monitor_schedule import MonitorSchedule
from app.schemas.monitor_schedule import BulkScheduleCreate, MonitorScheduleCreate
from app.services.schedule_service import schedule_service


def _seed_monitor_item(db):
    suffix = uuid4().hex[:8]
    business = Business(
        business_id=f"monitoring-mode-biz-{suffix}",
        business_type_id="13",
        name="Monitoring Mode Biz",
        service_type="naver",
        is_enabled=True,
    )
    db.add(business)
    db.commit()
    db.refresh(business)

    item = BizItem(
        business_id=business.id,
        biz_item_id=f"monitoring-mode-item-{suffix}",
        name="Monitoring Mode Item",
        is_enabled=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_schedule_service_create_defaults_to_anonymous(test_db_session):
    item = _seed_monitor_item(test_db_session)

    schedule = schedule_service.create(
        test_db_session,
        MonitorScheduleCreate(
            biz_item_id=item.id,
            date="2026-05-20",
            times=["10:00"],
        ),
    )

    assert schedule.monitoring_mode == "anonymous"


def test_schedule_service_create_bulk_defaults_to_anonymous(test_db_session):
    item = _seed_monitor_item(test_db_session)

    schedules = schedule_service.create_bulk(
        test_db_session,
        BulkScheduleCreate(
            biz_item_id=item.id,
            dates=["2026-05-21", "2026-05-22"],
            times=["11:00"],
        ),
    )

    assert schedules
    assert all(schedule.monitoring_mode == "anonymous" for schedule in schedules)


def test_init_extra_tables_backfills_all_existing_modes_to_anonymous(test_db_session):
    item = _seed_monitor_item(test_db_session)

    legacy = MonitorSchedule(
        biz_item_id=item.id,
        date="2026-05-23",
        times='["09:00"]',
        is_enabled=True,
        monitoring_mode="legacy",
    )
    null_mode = MonitorSchedule(
        biz_item_id=item.id,
        date="2026-05-24",
        times='["10:00"]',
        is_enabled=True,
        monitoring_mode="anonymous",
    )
    invalid = MonitorSchedule(
        biz_item_id=item.id,
        date="2026-05-25",
        times='["11:00"]',
        is_enabled=True,
        monitoring_mode="legacy",
    )
    test_db_session.add_all([legacy, null_mode, invalid])
    test_db_session.commit()

    test_db_session.execute(
        text("UPDATE monitor_schedules SET monitoring_mode = NULL WHERE id = :id"),
        {"id": null_mode.id},
    )
    test_db_session.execute(
        text("UPDATE monitor_schedules SET monitoring_mode = 'monitor' WHERE id = :id"),
        {"id": invalid.id},
    )
    test_db_session.commit()

    repair_monitor_schedule_monitoring_mode(test_db_session)
    repair_monitor_schedule_monitoring_mode(test_db_session)

    rows = test_db_session.execute(
        text(
            "SELECT monitoring_mode FROM monitor_schedules "
            "WHERE biz_item_id = :biz_item_id ORDER BY date"
        ),
        {"biz_item_id": item.id},
    ).scalars().all()

    assert rows == ["anonymous", "anonymous", "anonymous"]
