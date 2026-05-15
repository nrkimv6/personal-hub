"""Write normalized availability results to MonitoringEvent."""

from datetime import datetime
from typing import Any, Optional

from app.modules.availability.services.state import (
    determine_availability_status,
    event_type_for_status,
)
from app.modules.availability.types import AvailabilityCheckResult, AvailabilitySlot
from app.services.event_logger import EventLogger


def serialize_slot(slot: AvailabilitySlot) -> dict[str, Any]:
    data = dict(slot.raw or {})
    data.update(
        {
            "sourceType": slot.source_type,
            "availableCount": slot.available_count,
        }
    )
    if slot.label is not None:
        data["label"] = slot.label
    if slot.slot_id is not None:
        data["slotId"] = slot.slot_id
    return data


def write_availability_event(
    schedule_id: int,
    result: AvailabilityCheckResult,
    *,
    timestamp: Optional[datetime] = None,
    event_logger: type[EventLogger] = EventLogger,
) -> Any:
    status = determine_availability_status(
        result.slots,
        available_count=result.available_count,
        error_message=result.error_message,
    )
    slots_info = [serialize_slot(slot) for slot in result.slots]
    return event_logger.log_monitoring_event(
        schedule_id=schedule_id,
        event_type=event_type_for_status(status),
        status=status,
        available_count=result.available_count or 0,
        slots_info=slots_info,
        error_message=result.error_message,
        timestamp=timestamp,
        response_time_ms=result.response_time_ms,
        fetch_method=result.fetch_method,
    )
