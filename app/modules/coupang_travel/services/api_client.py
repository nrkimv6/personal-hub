"""
쿠팡 여행상품 vendor-items API 클라이언트.

Playwright 브라우저 탭에서 fetch()를 호출하여 쿠팡 로그인 쿠키를 활용합니다.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# 재시도 기본 딜레이 (초). 지수 백오프: delay * 2^(retry-1) → 10s, 20s, 40s
_BASE_RETRY_DELAY = 10.0
_MAX_RETRIES = 3


@dataclass
class VendorItem:
    vendor_item_name: str
    sale_status: str
    stock_count: int


class CoupangApiClient:
    """쿠팡 vendor-items REST API 클라이언트 (Playwright fetch 경로)."""

    async def fetch_vendor_items(
        self,
        product_id: str,
        vendor_item_package_id: str,
        select_date: str,
        page: "Page",
    ) -> Optional[List[VendorItem]]:
        """vendor-items API를 호출하여 VendorItem 목록을 반환.

        Args:
            product_id: 쿠팡 상품 ID
            vendor_item_package_id: 벤더 아이템 패키지 ID
            select_date: 조회 날짜 (YYYY-MM-DD)
            page: Playwright Page (로그인 쿠키 컨텍스트)

        Returns:
            VendorItem 리스트, 모든 재시도 실패 시 None
        """
        url = f"https://trip.coupang.com/api/products/{product_id}/vendor-items"
        referer = f"https://trip.coupang.com/tp/products/{product_id}"

        js_code = """
        async ({ url, body, referer }) => {
            const resp = await fetch(url, {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'origin': 'https://trip.coupang.com',
                    'referer': referer,
                    'content-type': 'application/json;charset=UTF-8',
                },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            return { status: resp.status, data };
        }
        """

        body = {
            "vendorItemPackageId": vendor_item_package_id,
            "productType": "TICKET",
            "selectDate": select_date,
        }

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                result = await page.evaluate(
                    js_code,
                    {"url": url, "body": body, "referer": referer},
                )

                status = result.get("status")
                data = result.get("data", {})

                if status == 405:
                    logger.warning(
                        "[CoupangApiClient] 405 응답 — page.reload() 후 재시도 (attempt=%d)",
                        attempt,
                    )
                    await page.reload()
                    delay = _BASE_RETRY_DELAY * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                    continue

                if status != 200:
                    raise RuntimeError(f"HTTP {status}: {data}")

                return self._parse_vendor_items(data)

            except Exception as e:
                logger.warning(
                    "[CoupangApiClient] 호출 실패 (attempt=%d/%d): %s",
                    attempt,
                    _MAX_RETRIES,
                    e,
                )
                if attempt < _MAX_RETRIES:
                    delay = _BASE_RETRY_DELAY * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)

        logger.error(
            "[CoupangApiClient] 최대 재시도 초과 (product_id=%s, date=%s)",
            product_id,
            select_date,
        )
        return None

    def _parse_vendor_items(self, data: dict) -> List[VendorItem]:
        """API 응답에서 VendorItem 리스트 추출."""
        items: List[VendorItem] = []
        travel_items = data.get("travelItems") or []

        for travel in travel_items:
            vendor_items = travel.get("vendorItems") or []
            for vi in vendor_items:
                items.append(
                    VendorItem(
                        vendor_item_name=vi.get("vendorItemName", ""),
                        sale_status=vi.get("saleStatus", ""),
                        stock_count=vi.get("stockCount", 0),
                    )
                )

        return items
