"""
모니터링 서비스 통합 테스트 (T3)
- 실제 CoupangMonitorService + mock CoupangApiClient
- NotificationService는 send_telegram만 mock (외부 호출 차단)
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.modules.coupang_travel.services.api_client import CoupangApiClient, VendorItem
from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService
from app.shared.notification import NotificationService


@pytest.mark.asyncio
async def test_monitor_check_pipeline():
    """실제 CoupangMonitorService로 2회 호출 파이프라인 검증."""
    # API 클라이언트만 mock
    mock_api = AsyncMock(spec=CoupangApiClient)
    mock_api.fetch_vendor_items = AsyncMock()

    # NotificationService: send_telegram만 차단
    notification_service = NotificationService()

    spy_calls = []

    async def fake_send(msg, send_desktop=False):
        spy_calls.append(msg)

    with patch.object(notification_service, "send_notification_message", side_effect=fake_send):
        service = CoupangMonitorService(mock_api, notification_service)

        # 1회차: 초기화 (상태만 저장, 알림 없음)
        mock_api.fetch_vendor_items.return_value = [
            VendorItem(vendor_item_name="옵션A", sale_status="SOLD_OUT", stock_count=0)
        ]
        changes1 = await service.check_and_notify("123", "pkg", ["2026-04-10"], AsyncMock())
        assert changes1 == []
        assert len(spy_calls) == 0

        # 2회차: 상태 변경 (알림 발송)
        mock_api.fetch_vendor_items.return_value = [
            VendorItem(vendor_item_name="옵션A", sale_status="ON_SALE", stock_count=3)
        ]
        changes2 = await service.check_and_notify("123", "pkg", ["2026-04-10"], AsyncMock())
        assert len(changes2) == 1
        assert len(spy_calls) == 1
        assert "[쿠팡]" in spy_calls[0]
