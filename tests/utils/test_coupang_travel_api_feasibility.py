import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.coupang_travel_api_feasibility import (  # noqa: E402
    load_coupang_cookies_from_storage_state,
    summarize_vendor_items_response,
)


def test_summarize_vendor_items_response_with_expected_schema():
    payload = {
        "travelItems": [
            {
                "vendorItems": [
                    {
                        "vendorItemName": "Option A",
                        "saleStatus": "SALE",
                        "stockCount": 3,
                        "vendorItemId": 101,
                    }
                ]
            }
        ]
    }

    summary = summarize_vendor_items_response(payload)

    assert summary["has_travelItems"] is True
    assert summary["travel_items_count"] == 1
    assert summary["vendor_items_count"] == 1
    assert summary["field_presence"]["vendorItemName"] is True
    assert summary["field_presence"]["saleStatus"] is True
    assert summary["field_presence"]["stockCount"] is True
    assert summary["field_presence"]["vendorItemId"] is True


def test_summarize_vendor_items_response_with_missing_path():
    payload = {"message": "unauthorized"}

    summary = summarize_vendor_items_response(payload)

    assert summary["has_travelItems"] is False
    assert summary["travel_items_count"] == 0
    assert summary["vendor_items_count"] == 0
    assert summary["field_presence"]["saleStatus"] is False


def test_load_coupang_cookies_from_storage_state_filters_domains(tmp_path: Path):
    storage_state = {
        "cookies": [
            {"name": "sid", "value": "abc", "domain": ".trip.coupang.com"},
            {"name": "x", "value": "1", "domain": ".example.com"},
            {"name": "cid", "value": "def", "domain": ".coupang.com"},
        ]
    }
    path = tmp_path / "state.json"
    path.write_text(json.dumps(storage_state), encoding="utf-8")

    cookies = load_coupang_cookies_from_storage_state(path)

    assert cookies == {"sid": "abc", "cid": "def"}
