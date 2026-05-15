from app.modules.availability.services.state import determine_availability_status
from app.modules.coupang_travel.services.api_client import VendorItem
from app.modules.coupang_travel.services.availability_adapter import (
    vendor_items_to_availability_result,
)


def test_coupang_adapter_RIGHT_stock_sale_maps_available():
    result = vendor_items_to_availability_result(
        [
            VendorItem(
                vendor_item_name="옵션A",
                sale_status="ON_SALE",
                stock_count=3,
            )
        ]
    )

    assert result.source_type == "coupang"
    assert result.available_count == 1
    assert determine_availability_status(
        result.slots,
        available_count=result.available_count,
    ) == "available"
    assert result.slots[0].available_count == 3
    assert result.slots[0].label == "옵션A"


def test_coupang_adapter_BOUNDARY_soldout_or_zero_maps_no_slots():
    result = vendor_items_to_availability_result(
        [
            VendorItem(
                vendor_item_name="품절 옵션",
                sale_status="SOLDOUT",
                stock_count=2,
            ),
            VendorItem(
                vendor_item_name="재고 없음",
                sale_status="ON_SALE",
                stock_count=0,
            ),
        ]
    )

    assert result.available_count == 0
    assert [slot.available_count for slot in result.slots] == [0, 0]
    assert determine_availability_status(
        result.slots,
        available_count=result.available_count,
    ) == "no_slots"


def test_coupang_adapter_RIGHT_preserves_raw_keys_in_slots_info():
    result = vendor_items_to_availability_result(
        [
            VendorItem(
                vendor_item_name="옵션A",
                sale_status="SOLD_OUT",
                stock_count=0,
            )
        ]
    )

    raw = result.slots[0].raw
    assert raw["vendorItemName"] == "옵션A"
    assert raw["saleStatus"] == "SOLD_OUT"
    assert raw["stockCount"] == 0
