"""
모니터링 서비스 통합 테스트 (T3)
- CoupangMonitorService + EventLogger DB 기록 검증
"""
import json
from datetime import datetime
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.modules.coupang_travel.services.api_client import CoupangApiClient, VendorItem
from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService
from app.shared.notification import NotificationService


@pytest.fixture
def integration_session_factory():
    from app.models.base import Base
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule
    from app.models.monitoring_event import MonitoringEvent

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
    yield factory
    engine.dispose()


def _create_coupang_schedule(session_factory) -> int:
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule

    db = session_factory()
    try:
        business = Business(
            business_id="cp:int-test-1",
            name="통합테스트 쿠팡",
            service_type="coupang",
        )
        db.add(business)
        db.flush()

        item = BizItem(
            business_id=business.id,
            biz_item_id="1000001",
            name="통합테스트 아이템",
        )
        db.add(item)
        db.flush()

        schedule = MonitorSchedule(
            biz_item_id=item.id,
            date="2026-05-01",
            is_enabled=True,
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        return schedule.id
    finally:
        db.close()


@pytest.mark.asyncio
async def test_event_logging_writes_to_db(integration_session_factory):
    from app.models.monitoring_event import MonitoringEvent

    schedule_id = _create_coupang_schedule(integration_session_factory)
    mock_api = AsyncMock(spec=CoupangApiClient)
    mock_api.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="SOLD_OUT", stock_count=0)
    ])
    notification_service = NotificationService()

    with patch.object(notification_service, "send_notification_message", AsyncMock()):
        with patch("app.services.event_logger.SessionLocal", integration_session_factory):
            service = CoupangMonitorService(mock_api, notification_service)
            await service.check_and_notify("1000001", "pkg", ["2026-05-01"], AsyncMock(), schedule_id=schedule_id)

    db = integration_session_factory()
    try:
        events = db.query(MonitoringEvent).all()
        assert len(events) == 1
        assert events[0].schedule_id == schedule_id
        assert events[0].status == "no_slots"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_event_logging_skips_when_schedule_id_is_none(integration_session_factory):
    from app.models.monitoring_event import MonitoringEvent

    mock_api = AsyncMock(spec=CoupangApiClient)
    mock_api.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="SOLD_OUT", stock_count=0)
    ])
    notification_service = NotificationService()

    with patch.object(notification_service, "send_notification_message", AsyncMock()):
        with patch("app.services.event_logger.SessionLocal", integration_session_factory):
            service = CoupangMonitorService(mock_api, notification_service)
            await service.check_and_notify("1000001", "pkg", ["2026-05-01"], AsyncMock(), schedule_id=None)

    db = integration_session_factory()
    try:
        assert db.query(MonitoringEvent).count() == 0
    finally:
        db.close()


@pytest.mark.asyncio
async def test_slots_info_roundtrip_as_list(integration_session_factory):
    from app.models.monitoring_event import MonitoringEvent

    schedule_id = _create_coupang_schedule(integration_session_factory)
    mock_api = AsyncMock(spec=CoupangApiClient)
    mock_api.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="ON_SALE", stock_count=2)
    ])
    notification_service = NotificationService()

    with patch.object(notification_service, "send_notification_message", AsyncMock()):
        with patch("app.services.event_logger.SessionLocal", integration_session_factory):
            service = CoupangMonitorService(mock_api, notification_service)
            await service.check_and_notify("1000001", "pkg", ["2026-05-01"], AsyncMock(), schedule_id=schedule_id)

    db = integration_session_factory()
    try:
        event = db.query(MonitoringEvent).first()
        assert event is not None
        assert isinstance(event.slots_info, str)
        parsed = json.loads(event.slots_info)
        assert isinstance(parsed, list)
        assert parsed[0]["vendorItemName"] == "옵션A"
        assert parsed[0]["saleStatus"] == "ON_SALE"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_event_logging_respects_prefetched_checked_at(integration_session_factory):
    from app.models.monitoring_event import MonitoringEvent

    schedule_id = _create_coupang_schedule(integration_session_factory)
    checked_at = datetime(2026, 4, 15, 10, 0, 0)
    mock_api = AsyncMock(spec=CoupangApiClient)
    notification_service = NotificationService()

    with patch.object(notification_service, "send_notification_message", AsyncMock()):
        with patch("app.services.event_logger.SessionLocal", integration_session_factory):
            service = CoupangMonitorService(mock_api, notification_service)
            await service.check_and_notify(
                "1000001",
                "pkg",
                ["2026-05-01"],
                prefetched_items=[VendorItem(vendor_item_name="옵션A", sale_status="SOLD_OUT", stock_count=0)],
                prefetched_checked_at=checked_at,
                schedule_id=schedule_id,
            )

    db = integration_session_factory()
    try:
        event = db.query(MonitoringEvent).first()
        assert event is not None
        assert event.timestamp == checked_at
    finally:
        db.close()
