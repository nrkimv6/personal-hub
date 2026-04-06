"""
모니터링 서비스 테스트 (RIGHT-BICEP: R, B, I, C)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

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
