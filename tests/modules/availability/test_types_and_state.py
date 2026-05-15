from app.modules.availability.services.state import (
    determine_availability_status,
    event_type_for_status,
)
from app.modules.availability.types import AvailabilityCheckResult, AvailabilitySlot


def test_availability_status_RIGHT_available_when_any_slot_positive():
    slots = [
        AvailabilitySlot(source_type="popply", available_count=0),
        AvailabilitySlot(source_type="popply", available_count=2),
    ]

    result = AvailabilityCheckResult(source_type="popply", slots=slots)

    assert result.available_count == 2
    assert determine_availability_status(result.slots) == "available"
    assert event_type_for_status("available") == "slot_detected"


def test_availability_status_BOUNDARY_empty_slots_no_slots():
    result = AvailabilityCheckResult(source_type="popply", slots=[])

    assert result.available_count == 0
    assert determine_availability_status(result.slots) == "no_slots"
    assert event_type_for_status("no_slots") == "check"


def test_availability_status_ERROR_invalid_input_returns_error():
    assert determine_availability_status(None) == "error"
    assert event_type_for_status("error") == "error"
