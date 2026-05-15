"""Availability status and event type mapping."""

from collections.abc import Sequence
from typing import Literal, Optional

from app.modules.availability.types import AvailabilitySlot, AvailabilityStatus


AvailabilityEventType = Literal["check", "slot_detected", "error"]


def determine_availability_status(
    slots: Sequence[AvailabilitySlot] | None,
    *,
    available_count: Optional[int] = None,
    error_message: Optional[str] = None,
) -> AvailabilityStatus:
    if error_message or slots is None:
        return "error"
    if available_count is not None:
        return "available" if available_count > 0 else "no_slots"
    return "available" if any(slot.is_available for slot in slots) else "no_slots"


def event_type_for_status(status: AvailabilityStatus) -> AvailabilityEventType:
    if status == "available":
        return "slot_detected"
    if status == "error":
        return "error"
    return "check"
