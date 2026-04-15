"""
모니터링 서비스 테스트 (RIGHT-BICEP: R, B, I, C)
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.modules.coupang_travel.services.api_client import VendorItem
from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService


def make_service():
    api_client = AsyncMock()
    notification_service = AsyncMock()
    notification_service.send_notification_message = AsyncMock()
    service = CoupangMonitorService(api_client, notification_service)
    return service, api_client, notification_service


def make_page():
    return AsyncMock()


@pytest.mark.asyncio
async def test_check_and_notify_initial_no_alert():
    """R: 최초 호출 → StatusChange 빈 리스트, notification 호출 0회"""
    service, api_client, notification = make_service()
    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="SOLD_OUT", stock_count=0)
    ])

    changes = await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page())

    assert changes == []
    notification.send_notification_message.assert_not_called()


@pytest.mark.asyncio
async def test_check_and_notify_status_change():
    """R: 2회 연속 호출 (1회차 초기화, 2회차 상태 변경) → StatusChange 1개, notification 1회"""
    service, api_client, notification = make_service()

    # 1회차: SOLD_OUT
    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="SOLD_OUT", stock_count=0)
    ])
    await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page())

    # 2회차: ON_SALE
    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="ON_SALE", stock_count=2)
    ])
    changes = await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page())

    assert len(changes) == 1
    assert changes[0].old_status == "SOLD_OUT"
    assert changes[0].new_status == "ON_SALE"
    notification.send_notification_message.assert_called_once()

    msg_arg = notification.send_notification_message.call_args[0][0]
    assert "[쿠팡]" in msg_arg
    assert "SOLD_OUT" in msg_arg
    assert "ON_SALE" in msg_arg


@pytest.mark.asyncio
async def test_check_and_notify_kakao_bypasses_notify_times():
    """메가뷰티쇼 날짜는 notify_times 밖이어도 Kakao 알림이 간다."""
    service, api_client, notification = make_service()

    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="SOLD_OUT", stock_count=0)
    ])
    await service.check_and_notify("123", "pkg", ["2026-04-17"], make_page())

    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="ON_SALE", stock_count=1)
    ])
    with patch.object(service, "_is_within_notify_times", return_value=False):
        changes = await service.check_and_notify("123", "pkg", ["2026-04-17"], make_page())

    assert len(changes) == 1
    notification.send_notification_message.assert_called_once()
    kwargs = notification.send_notification_message.call_args.kwargs
    assert kwargs["send_telegram"] is False
    assert kwargs["send_desktop"] is False
    assert kwargs["send_kakao"] is True


@pytest.mark.asyncio
async def test_check_and_notify_stock_change():
    """I: saleStatus 동일 + stockCount 변경 → StatusChange 1개"""
    service, api_client, notification = make_service()

    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="ON_SALE", stock_count=5)
    ])
    await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page())

    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="ON_SALE", stock_count=2)
    ])
    changes = await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page())

    assert len(changes) == 1
    assert changes[0].old_stock == 5
    assert changes[0].new_stock == 2


@pytest.mark.asyncio
async def test_check_and_notify_no_change():
    """B: 상태 동일 2회 → StatusChange 빈 리스트, notification 0회"""
    service, api_client, notification = make_service()

    same_items = [VendorItem(vendor_item_name="옵션A", sale_status="ON_SALE", stock_count=3)]
    api_client.fetch_vendor_items = AsyncMock(return_value=same_items)

    await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page())
    changes = await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page())

    assert changes == []
    notification.send_notification_message.assert_not_called()


@pytest.mark.asyncio
async def test_check_and_notify_blank_sale_status_counts_available():
    service, api_client, _ = make_service()
    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="", stock_count=1)
    ])

    with patch("app.modules.coupang_travel.services.monitor_service.EventLogger.log_monitoring_event") as log_event:
        await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page(), schedule_id=13)

    assert log_event.call_count == 1
    kwargs = log_event.call_args.kwargs
    assert kwargs["status"] == "available"
    assert kwargs["event_type"] == "slot_detected"
    assert kwargs["available_count"] == 1


@pytest.mark.asyncio
async def test_check_and_notify_explicit_soldout_keeps_no_slots():
    service, api_client, _ = make_service()
    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="SOLDOUT", stock_count=1)
    ])

    with patch("app.modules.coupang_travel.services.monitor_service.EventLogger.log_monitoring_event") as log_event:
        await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page(), schedule_id=14)

    assert log_event.call_count == 1
    kwargs = log_event.call_args.kwargs
    assert kwargs["status"] == "no_slots"
    assert kwargs["event_type"] == "check"
    assert kwargs["available_count"] == 0


@pytest.mark.asyncio
async def test_check_and_notify_logs_event_with_schedule_id():
    service, api_client, _ = make_service()
    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="SOLD_OUT", stock_count=0)
    ])

    with patch("app.modules.coupang_travel.services.monitor_service.EventLogger.log_monitoring_event") as log_event:
        await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page(), schedule_id=10)

    assert log_event.call_count == 1
    kwargs = log_event.call_args.kwargs
    assert kwargs["schedule_id"] == 10
    assert kwargs["status"] == "no_slots"


@pytest.mark.asyncio
async def test_check_and_notify_skips_logging_without_schedule_id():
    service, api_client, _ = make_service()
    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="SOLD_OUT", stock_count=0)
    ])

    with patch("app.modules.coupang_travel.services.monitor_service.EventLogger.log_monitoring_event") as log_event:
        await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page(), schedule_id=None)

    log_event.assert_not_called()


@pytest.mark.asyncio
async def test_check_and_notify_logs_error_on_api_failure_with_schedule_id():
    service, api_client, _ = make_service()
    api_client.fetch_vendor_items = AsyncMock(return_value=None)

    with patch("app.modules.coupang_travel.services.monitor_service.EventLogger.log_monitoring_event") as log_event:
        await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page(), schedule_id=11)

    assert log_event.call_count == 1
    kwargs = log_event.call_args.kwargs
    assert kwargs["schedule_id"] == 11
    assert kwargs["status"] == "error"
    assert kwargs["slots_info"] is None


@pytest.mark.asyncio
async def test_check_and_notify_slots_info_not_double_serialized():
    service, api_client, _ = make_service()
    api_client.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="옵션A", sale_status="ON_SALE", stock_count=2)
    ])

    with patch("app.modules.coupang_travel.services.monitor_service.EventLogger.log_monitoring_event") as log_event:
        await service.check_and_notify("123", "pkg", ["2026-04-10"], make_page(), schedule_id=12)

    kwargs = log_event.call_args.kwargs
    assert isinstance(kwargs["slots_info"], list)
    assert kwargs["slots_info"][0]["vendorItemName"] == "옵션A"
