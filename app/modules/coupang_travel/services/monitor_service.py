"""
쿠팡 여행상품 모니터링 서비스.

상태 추적, 변경 감지, 알림 발송을 담당합니다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

from app.modules.coupang_travel.services.api_client import CoupangApiClient, VendorItem

if TYPE_CHECKING:
    from playwright.async_api import Page
    from app.shared.notification import NotificationService

logger = logging.getLogger(__name__)


@dataclass
class VendorItemStatus:
    sale_status: str
    stock_count: int
    last_update: datetime = field(default_factory=datetime.now)


@dataclass
class StatusChange:
    date: str
    item_name: str
    old_status: str
    new_status: str
    old_stock: int
    new_stock: int


def _make_vendor_key(vi: VendorItem, index: int) -> str:
    """안정적인 상태 키 생성. 이름 기반 fallback."""
    if vi.vendor_item_name:
        return vi.vendor_item_name
    return f"item_{index}"


class CoupangMonitorService:
    """쿠팡 여행상품 상태 추적 + 변경 감지 + 알림 서비스."""

    def __init__(
        self,
        api_client: CoupangApiClient,
        notification_service: "NotificationService",
    ):
        self._api_client = api_client
        self._notification_service = notification_service
        # 키: "{product_id}_{date}_{vendor_key}" → VendorItemStatus
        self._previous_statuses: Dict[str, VendorItemStatus] = {}

    async def check_and_notify(
        self,
        product_id: str,
        vendor_item_package_id: str,
        dates: List[str],
        page: "Page",
    ) -> List[StatusChange]:
        """각 date별 상태를 체크하고 변경 시 알림 발송.

        최초 호출(키 없음)은 상태 저장만 하고 알림은 보내지 않는다.

        Returns:
            변경된 StatusChange 목록
        """
        changes: List[StatusChange] = []

        for date in dates:
            items = await self._api_client.fetch_vendor_items(
                product_id=product_id,
                vendor_item_package_id=vendor_item_package_id,
                select_date=date,
                page=page,
            )
            if items is None:
                logger.warning(
                    "[CoupangMonitorService] API 응답 없음 (product_id=%s, date=%s)",
                    product_id,
                    date,
                )
                continue

            for idx, vi in enumerate(items):
                vendor_key = _make_vendor_key(vi, idx)
                state_key = f"{product_id}_{date}_{vendor_key}"
                current = VendorItemStatus(
                    sale_status=vi.sale_status,
                    stock_count=vi.stock_count,
                )

                if state_key not in self._previous_statuses:
                    # 최초: 상태만 저장, 알림 없음
                    self._previous_statuses[state_key] = current
                    continue

                prev = self._previous_statuses[state_key]
                status_changed = prev.sale_status != current.sale_status
                stock_changed = prev.stock_count != current.stock_count

                if status_changed or stock_changed:
                    change = StatusChange(
                        date=date,
                        item_name=vi.vendor_item_name,
                        old_status=prev.sale_status,
                        new_status=current.sale_status,
                        old_stock=prev.stock_count,
                        new_stock=current.stock_count,
                    )
                    changes.append(change)
                    self._previous_statuses[state_key] = current

                    await self._send_notification(change)

        return changes

    async def _send_notification(self, change: StatusChange) -> None:
        """변경 알림 발송."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = (
            f"[쿠팡] 상태 변경: [{change.date}] {change.item_name}\n"
            f"판매상태: {change.old_status} → {change.new_status}\n"
            f"재고: {change.new_stock}개\n"
            f"감지 시각: {now_str}"
        )
        try:
            await self._notification_service.send_notification_message(
                message, send_desktop=True
            )
        except Exception as e:
            logger.error("[CoupangMonitorService] 알림 발송 실패: %s", e)
