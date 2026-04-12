"""
쿠팡 여행상품 모니터링 서비스.

상태 추적, 변경 감지, 알림 발송, DB 이벤트 로깅을 담당합니다.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

from app.modules.coupang_travel.services.api_client import CoupangApiClient, VendorItem
from app.services.event_logger import EventLogger

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
        db_logging: bool = True,
    ):
        self._api_client = api_client
        self._notification_service = notification_service
        self._db_logging = db_logging
        # 키: "{product_id}_{date}_{vendor_key}" -> VendorItemStatus
        self._previous_statuses: Dict[str, VendorItemStatus] = {}

    async def check_and_notify(
        self,
        product_id: str,
        vendor_item_package_id: str,
        dates: List[str],
        page: Optional["Page"] = None,
        schedule_id: Optional[int] = None,
        prefetched_items: Optional[List[VendorItem]] = None,
        prefetched_response_time_ms: float = 0.0,
    ) -> List[StatusChange]:
        """각 date별 상태를 체크하고 변경 시 알림 발송.

        최초 호출(키 없음)은 상태 저장만 하고 알림은 보내지 않는다.

        Args:
            prefetched_items: HTTP 클라이언트로 미리 가져온 아이템 목록.
                              제공 시 page 경로 skip. dates는 단일 date여야 함.
            prefetched_response_time_ms: prefetched_items 획득에 걸린 시간.

        Returns:
            변경된 StatusChange 목록
        """
        changes: List[StatusChange] = []

        for date in dates:
            if prefetched_items is not None:
                # HTTP 클라이언트로 미리 가져온 아이템 사용
                items = prefetched_items
                response_time_ms = prefetched_response_time_ms
            else:
                if page is None:
                    logger.error(
                        "[CoupangMonitorService] page와 prefetched_items 모두 없음 (product_id=%s, date=%s)",
                        product_id, date,
                    )
                    continue
                started_at = time.perf_counter()
                items = await self._api_client.fetch_vendor_items(
                    product_id=product_id,
                    vendor_item_package_id=vendor_item_package_id,
                    select_date=date,
                    page=page,
                )
                response_time_ms = (time.perf_counter() - started_at) * 1000

            if items is None:
                logger.warning(
                    "[CoupangMonitorService] API 응답 없음 (product_id=%s, date=%s)",
                    product_id,
                    date,
                )
                self._log_monitoring_event(
                    schedule_id=schedule_id,
                    status="error",
                    available_count=0,
                    slots_info=None,
                    error_message="Coupang vendor-items API returned no response",
                    response_time_ms=response_time_ms,
                )
                continue

            date_changes: List[StatusChange] = []
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
                    date_changes.append(change)
                    self._previous_statuses[state_key] = current
                    await self._send_notification(change)

            slots_info = self._build_slots_info(items)
            available_count = sum(1 for item in items if self._is_item_available(item))
            status_name = self._map_monitor_status(items, date_changes, api_error=False)
            self._log_monitoring_event(
                schedule_id=schedule_id,
                status=status_name,
                available_count=available_count,
                slots_info=slots_info,
                response_time_ms=response_time_ms,
            )

        return changes

    @staticmethod
    def _is_item_available(item: VendorItem) -> bool:
        return item.sale_status.upper() == "ON_SALE" and item.stock_count > 0

    @staticmethod
    def _build_slots_info(items: List[VendorItem]) -> List[dict]:
        """MonitoringEvent.slots_info에 저장할 구조를 생성."""
        return [
            {
                "vendorItemName": item.vendor_item_name,
                "saleStatus": item.sale_status,
                "stockCount": item.stock_count,
            }
            for item in items
        ]

    def _map_monitor_status(
        self,
        items: List[VendorItem],
        changes: List[StatusChange],
        api_error: bool = False,
    ) -> str:
        """쿠팡 체크 결과를 공통 이벤트 상태로 정규화."""
        if api_error:
            return "error"
        if any(self._is_item_available(item) for item in items):
            return "available"
        if changes:
            return "success"
        return "no_slots"

    def _log_monitoring_event(
        self,
        schedule_id: Optional[int],
        status: str,
        available_count: int,
        slots_info: Optional[List[dict]],
        response_time_ms: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> None:
        if not self._db_logging:
            return
        if schedule_id is None:
            logger.warning(
                "[CoupangMonitorService] schedule_id 없음으로 DB 이벤트 로깅 생략"
            )
            return

        event_type = "check"
        if status == "available":
            event_type = "slot_detected"
        elif status == "error":
            event_type = "error"

        try:
            EventLogger.log_monitoring_event(
                schedule_id=schedule_id,
                event_type=event_type,
                status=status,
                available_count=available_count,
                slots_info=slots_info,
                error_message=error_message,
                response_time_ms=response_time_ms,
            )
        except Exception as e:
            logger.error(
                "[CoupangMonitorService] DB 이벤트 로깅 실패 (schedule_id=%s): %s",
                schedule_id,
                e,
            )

    async def _send_notification(self, change: StatusChange) -> None:
        """변경 알림 발송."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = (
            f"[쿠팡] 상태 변경: [{change.date}] {change.item_name}\n"
            f"판매상태: {change.old_status} -> {change.new_status}\n"
            f"재고: {change.new_stock}개\n"
            f"감지 시각: {now_str}"
        )
        try:
            await self._notification_service.send_notification_message(
                message, send_desktop=True
            )
        except Exception as e:
            logger.error("[CoupangMonitorService] 알림 발송 실패: %s", e)
