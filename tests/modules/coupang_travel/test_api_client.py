"""
API 클라이언트 테스트 (RIGHT-BICEP: R, E, B)
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.coupang_travel.services.api_client import CoupangApiClient, VendorItem


NORMAL_RESPONSE = {
    "status": 200,
    "data": {
        "travelItems": [
            {
                "vendorItems": [
                    {"vendorItemName": "옵션A", "saleStatus": "ON_SALE", "stockCount": 3},
                    {"vendorItemName": "옵션B", "saleStatus": "SOLD_OUT", "stockCount": 0},
                ]
            }
        ]
    }
}


def make_page_mock(responses):
    """responses 리스트를 순서대로 반환하는 mock Page."""
    page = AsyncMock()
    page.evaluate = AsyncMock(side_effect=responses)
    page.reload = AsyncMock()
    return page


@pytest.mark.asyncio
async def test_fetch_vendor_items_right():
    """R: 정상 응답 → VendorItem 파싱"""
    page = make_page_mock([NORMAL_RESPONSE])
    client = CoupangApiClient()

    with patch("asyncio.sleep", return_value=None):
        items = await client.fetch_vendor_items("123", "pkg456", "2026-04-10", page)

    assert items is not None
    assert len(items) == 2
    assert items[0].vendor_item_name == "옵션A"
    assert items[0].sale_status == "ON_SALE"
    assert items[0].stock_count == 3
    assert isinstance(items[0], VendorItem)


@pytest.mark.asyncio
async def test_fetch_vendor_items_error_retry():
    """E: 1~2회 에러 후 3회째 성공 → 결과 반환"""
    page = make_page_mock([
        Exception("network error"),
        Exception("timeout"),
        NORMAL_RESPONSE,
    ])
    client = CoupangApiClient()

    with patch("asyncio.sleep", return_value=None):
        items = await client.fetch_vendor_items("123", "pkg456", "2026-04-10", page)

    assert items is not None
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_vendor_items_405_handling():
    """E: 405 응답 → page.reload() 호출 후 재시도"""
    response_405 = {"status": 405, "data": {"error": "Method Not Allowed"}}
    page = make_page_mock([response_405, NORMAL_RESPONSE])
    client = CoupangApiClient()

    with patch("asyncio.sleep", return_value=None):
        items = await client.fetch_vendor_items("123", "pkg456", "2026-04-10", page)

    page.reload.assert_called_once()
    assert items is not None


@pytest.mark.asyncio
async def test_fetch_vendor_items_all_retries_fail():
    """B: 3회 모두 실패 → None 반환"""
    page = make_page_mock([
        Exception("fail1"),
        Exception("fail2"),
        Exception("fail3"),
    ])
    client = CoupangApiClient()

    with patch("asyncio.sleep", return_value=None):
        items = await client.fetch_vendor_items("123", "pkg456", "2026-04-10", page)

    assert items is None
