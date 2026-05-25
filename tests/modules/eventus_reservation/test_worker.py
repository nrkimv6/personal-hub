"""Tests for EventusMonitorWorker — in-memory DB integration."""

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
from app.worker.eventus_monitor_worker import EventusMonitorWorker

_SOURCE_URL = "https://event-us.kr/age20scoffee/event/126341"


def _make_engine_and_factory():
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
    return engine, factory


def _seed_schedule(factory, *, source_url: str = _SOURCE_URL, bundle_id: str = "bundle_morning_A") -> int:
    db = factory()
    try:
        business = Business(
            business_id="eventus:126341",
            name="Age20s Coffee",
            service_type="eventus",
        )
        db.add(business)
        db.flush()
        item = BizItem(
            business_id=business.id,
            biz_item_id="eventus:126341",
            name="20대 커피챗",
            base_url=source_url,
            extra_desc_json=json.dumps({
                "event_id": "126341",
                "source_url": source_url,
                "organizer_slug": "age20scoffee",
                "selected_bundle_id": bundle_id,
            }),
        )
        db.add(item)
        db.flush()
        schedule = MonitorSchedule(biz_item_id=item.id, date="2026-06-01", is_enabled=True)
        db.add(schedule)
        db.commit()
        return schedule.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# RIGHT: no-slots result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eventus_worker_records_monitoring_event_and_last_check_time(monkeypatch):
    """R: worker._check_schedule → MonitoringEvent 생성 + last_check_time 갱신."""
    engine, factory = _make_engine_and_factory()
    monkeypatch.setattr("app.worker.eventus_monitor_worker.SessionLocal", factory)
    monkeypatch.setattr("app.services.event_logger.SessionLocal", factory)

    schedule_id = _seed_schedule(factory)

    class FakeAdapter:
        async def check(self, **kwargs):
            return AvailabilityCheckResult(
                source_type="eventus",
                slots=[
                    AvailabilitySlot(
                        source_type="eventus",
                        available_count=0,
                        raw={"sourceType": "eventus", "bundleId": "bundle_morning_A"},
                    )
                ],
                fetch_method="anonymous_html",
            )

    class FakeNotification:
        async def send_notification_message(self, msg: str):
            pass

    worker = EventusMonitorWorker(
        adapter=FakeAdapter(),
        notification_service=FakeNotification(),
    )
    await worker._check_schedule({"id": schedule_id})

    db = factory()
    try:
        schedule = db.query(MonitorSchedule).filter(MonitorSchedule.id == schedule_id).one()
        event = db.query(MonitoringEvent).filter(MonitoringEvent.schedule_id == schedule_id).one()
        assert schedule.last_check_time is not None
        assert schedule.is_active is False
        assert schedule.run_status == "idle"
        assert event.status == "no_slots"
        assert event.available_count == 0
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# RIGHT: available result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eventus_worker_records_available_event(monkeypatch):
    """R: available 결과 → event.status='available'."""
    engine, factory = _make_engine_and_factory()
    monkeypatch.setattr("app.worker.eventus_monitor_worker.SessionLocal", factory)
    monkeypatch.setattr("app.services.event_logger.SessionLocal", factory)

    schedule_id = _seed_schedule(factory)

    class FakeAdapter:
        async def check(self, **kwargs):
            return AvailabilityCheckResult(
                source_type="eventus",
                slots=[
                    AvailabilitySlot(
                        source_type="eventus",
                        available_count=1,
                        raw={
                            "sourceType": "eventus",
                            "bundleId": "bundle_morning_A",
                            "availableCountKnown": False,
                        },
                    )
                ],
                fetch_method="anonymous_html",
            )

    notified: list[str] = []

    class FakeNotification:
        async def send_notification_message(self, msg: str):
            notified.append(msg)

    worker = EventusMonitorWorker(
        adapter=FakeAdapter(),
        notification_service=FakeNotification(),
    )
    await worker._check_schedule({"id": schedule_id})

    db = factory()
    try:
        event = db.query(MonitoringEvent).filter(MonitoringEvent.schedule_id == schedule_id).one()
        assert event.status == "available"
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# BOUNDARY: missing source_url — worker skips schedule gracefully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eventus_worker_skips_schedule_with_missing_source_url(monkeypatch):
    """B: source_url 없는 스케줄 → MonitoringEvent 미생성, 예외 없이 종료."""
    engine, factory = _make_engine_and_factory()
    monkeypatch.setattr("app.worker.eventus_monitor_worker.SessionLocal", factory)
    monkeypatch.setattr("app.services.event_logger.SessionLocal", factory)

    db = factory()
    try:
        business = Business(
            business_id="eventus:no-url",
            name="No URL",
            service_type="eventus",
        )
        db.add(business)
        db.flush()
        item = BizItem(
            business_id=business.id,
            biz_item_id="eventus:no-url",
            name="no url item",
            base_url=None,
            extra_desc_json="{}",
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
            raise AssertionError("should not be called")

    worker = EventusMonitorWorker(adapter=FakeAdapter(), notification_service=None)
    # Should return without raising
    await worker._check_schedule({"id": schedule_id})

    db = factory()
    try:
        count = db.query(MonitoringEvent).filter(MonitoringEvent.schedule_id == schedule_id).count()
        assert count == 0
    finally:
        db.close()
        engine.dispose()
