from datetime import datetime
from uuid import uuid4
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.biz_item import BizItem
from app.models.business import Business
from app.models.monitor_schedule import MonitorSchedule


def _seed_named_schedule(db_session, *, run_status, date, next_run_time=None):
    suffix = uuid4().hex[:8]
    business = Business(
        business_id=f"naver-business-ext-{suffix}",
        name="Named Access Biz",
        business_type_id=13,
        service_type="naver",
    )
    db_session.add(business)
    db_session.flush()

    biz_item = BizItem(
        business_id=business.id,
        biz_item_id=f"naver-item-ext-{suffix}",
        name="Named Access Item",
    )
    db_session.add(biz_item)
    db_session.flush()

    schedule = MonitorSchedule(
        biz_item_id=biz_item.id,
        service_account_id=None,
        date=date,
        time_range=None,
        times='["10:00"]',
        interval=30,
        is_enabled=True,
        run_status=run_status,
        next_run_time=next_run_time,
    )
    db_session.add(schedule)
    db_session.commit()

    return {
        "business": business,
        "biz_item": biz_item,
        "schedule_id": schedule.id,
    }


@pytest.mark.asyncio
async def test_load_active_schedules_reads_named_mapping_fields_from_real_db(test_db_session):
    from app.worker.naver_monitor_worker import NaverMonitorWorker

    seeded = _seed_named_schedule(
        test_db_session,
        run_status="pending",
        date="2026-04-24",
    )
    Session = sessionmaker(bind=test_db_session.get_bind())
    worker = NaverMonitorWorker()

    with patch("app.worker.naver_monitor_worker.SessionLocal", Session), patch.object(
        worker.__class__,
        "_get_today_kst",
        return_value="2026-04-24",
    ):
        await worker._load_active_schedules()

    schedule = worker._active_schedules[seeded["schedule_id"]]
    assert schedule["business_pk"] == seeded["business"].id
    assert schedule["naver_biz_item_id"] == seeded["biz_item"].biz_item_id
    assert schedule["business_name"] == seeded["business"].name
    assert schedule["naver_business_id"] == seeded["business"].business_id
    assert schedule["run_status"] == "queued"
    assert schedule["next_run_time"] is not None

    verify_db = Session()
    try:
        stored = verify_db.get(MonitorSchedule, seeded["schedule_id"])
        assert stored.run_status == "queued"
        assert stored.next_run_time is not None
    finally:
        verify_db.close()


@pytest.mark.asyncio
async def test_check_for_new_schedules_preserves_queue_fallback_with_named_mapping_fields(test_db_session):
    from app.worker.naver_monitor_worker import NaverMonitorWorker

    seeded = _seed_named_schedule(
        test_db_session,
        run_status="pending",
        date="2026-04-24",
        next_run_time=None,
    )
    Session = sessionmaker(bind=test_db_session.get_bind())
    worker = NaverMonitorWorker()

    with patch("app.worker.naver_monitor_worker.SessionLocal", Session), patch.object(
        worker.__class__,
        "_get_today_kst",
        return_value="2026-04-24",
    ):
        await worker._check_for_new_schedules()

    schedule = worker._active_schedules[seeded["schedule_id"]]
    assert schedule["business_pk"] == seeded["business"].id
    assert schedule["naver_biz_item_id"] == seeded["biz_item"].biz_item_id
    assert schedule["naver_business_id"] == seeded["business"].business_id
    assert schedule["run_status"] == "queued"
    assert schedule["next_run_time"] is not None

    verify_db = Session()
    try:
        stored = verify_db.get(MonitorSchedule, seeded["schedule_id"])
        assert stored.run_status == "queued"
        assert isinstance(stored.next_run_time, datetime)
    finally:
        verify_db.close()
