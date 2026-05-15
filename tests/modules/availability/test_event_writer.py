from datetime import datetime
from unittest.mock import Mock

from app.modules.availability.services.event_writer import (
    serialize_slot,
    write_availability_event,
)
from app.modules.availability.types import AvailabilityCheckResult, AvailabilitySlot


def test_event_writer_RIGHT_preserves_slots_info_json():
    slot = AvailabilitySlot(
        source_type="coupang",
        available_count=3,
        label="오전권",
        raw={
            "vendorItemName": "메가뷰티쇼 오전권",
            "saleStatus": "ON_SALE",
            "stockCount": 3,
        },
    )

    serialized = serialize_slot(slot)

    assert serialized["vendorItemName"] == "메가뷰티쇼 오전권"
    assert serialized["saleStatus"] == "ON_SALE"
    assert serialized["stockCount"] == 3
    assert serialized["sourceType"] == "coupang"
    assert serialized["availableCount"] == 3
    assert serialized["label"] == "오전권"


def test_event_writer_RIGHT_passes_keyword_args_to_log_monitoring_event():
    event_logger = Mock()
    timestamp = datetime(2026, 5, 15, 9, 30)
    result = AvailabilityCheckResult(
        source_type="popply",
        slots=[
            AvailabilitySlot(
                source_type="popply",
                available_count=1,
                raw={"scheduleGroup": "abc"},
            )
        ],
        response_time_ms=123.4,
        fetch_method="anonymous_api",
    )

    write_availability_event(
        42,
        result,
        timestamp=timestamp,
        event_logger=event_logger,
    )

    event_logger.log_monitoring_event.assert_called_once()
    kwargs = event_logger.log_monitoring_event.call_args.kwargs
    assert kwargs["schedule_id"] == 42
    assert kwargs["event_type"] == "slot_detected"
    assert kwargs["status"] == "available"
    assert kwargs["available_count"] == 1
    assert kwargs["slots_info"][0]["scheduleGroup"] == "abc"
    assert kwargs["response_time_ms"] == 123.4
    assert kwargs["fetch_method"] == "anonymous_api"
    assert kwargs["timestamp"] == timestamp
