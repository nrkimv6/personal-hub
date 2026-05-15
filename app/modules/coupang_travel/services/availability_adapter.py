"""Coupang vendor item adapter for the common availability contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from app.modules.availability.types import AvailabilityCheckResult, AvailabilitySlot
from app.modules.coupang_travel.services.api_client import VendorItem


SOURCE_TYPE = "coupang"
_NON_AVAILABLE_STATUSES = {"SOLDOUT", "SOLD_OUT", "STOP_SALE", "OFF_SALE"}


def is_vendor_item_available(item: VendorItem) -> bool:
    sale_status = (item.sale_status or "").upper()
    return item.stock_count > 0 and sale_status not in _NON_AVAILABLE_STATUSES


def vendor_item_to_slot(item: VendorItem) -> AvailabilitySlot:
    return AvailabilitySlot(
        source_type=SOURCE_TYPE,
        available_count=max(0, item.stock_count) if is_vendor_item_available(item) else 0,
        label=item.vendor_item_name,
        raw={
            "vendorItemName": item.vendor_item_name,
            "saleStatus": item.sale_status,
            "stockCount": item.stock_count,
        },
    )


def vendor_items_to_availability_result(
    items: Sequence[VendorItem],
    *,
    response_time_ms: Optional[float] = None,
    fetch_method: Optional[str] = None,
) -> AvailabilityCheckResult:
    slots = [vendor_item_to_slot(item) for item in items]
    return AvailabilityCheckResult(
        source_type=SOURCE_TYPE,
        slots=slots,
        available_count=sum(1 for item in items if is_vendor_item_available(item)),
        raw=list(items),
        response_time_ms=response_time_ms,
        fetch_method=fetch_method,
    )
