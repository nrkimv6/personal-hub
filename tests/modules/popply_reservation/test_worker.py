import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.business import Business
from app.models.biz_item import BizItem
from app.models.monitor_schedule import MonitorSchedule
from app.models.monitoring_event import MonitoringEvent
from app.modules.availability.types import AvailabilityCheckResult, AvailabilitySlot
from app.worker.popply_monitor_worker import PopplyMonitorWorker


@pytest.mark.asyncio
async def test_popply_worker_records_monitoring_event_and_last_check_time(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Business.__table__,
            BizItem.__table__,
            MonitorSchedule.__table__,
            MonitoringEvent.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=True)
    monkeypatch.setattr("app.worker.popply_monitor_worker.SessionLocal", factory)
    monkeypatch.setattr("app.services.event_logger.SessionLocal", factory)

    db = factory()
    try:
        business = Business(business_id="popply:4727", name="POPPLY", service_type="popply")
        db.add(business)
        db.flush()
        item = BizItem(
            business_id=business.id,
            biz_item_id="4727:q%2Fabc",
            name="POPPLY 4727",
            extra_desc_json=json.dumps(
                {
                    "store_id": "4727",
                    "reservation_type": "PRE",
                    "schedule_group": "q%2Fabc",
                }
            ),
        )
        db.add(item)
        db.flush()
        schedule = MonitorSchedule(biz_item_id=item.id, date="2026-06-01", is_enabled=True)
        db.add(schedule)
        db.commit()
        schedule_id = schedule.id
    finally:
        db.close()

    class FakeAdapter:
        async def check(self, **kwargs):
            return AvailabilityCheckResult(
                source_type="popply",
                slots=[AvailabilitySlot(source_type="popply", available_count=1)],
                fetch_method="anonymous_api",
            )

    worker = PopplyMonitorWorker(adapter=FakeAdapter())
    await worker._check_schedule({"id": schedule_id})

    db = factory()
    try:
        schedule = db.query(MonitorSchedule).filter(MonitorSchedule.id == schedule_id).one()
        event = db.query(MonitoringEvent).filter(MonitoringEvent.schedule_id == schedule_id).one()
        assert schedule.last_check_time is not None
        assert schedule.is_active is False
        assert event.status == "available"
        assert event.available_count == 1
    finally:
        db.close()
        engine.dispose()
