from app.modules.availability.services.change_detector import (
    detect_availability_change,
    next_status_after_check,
)


def test_change_detector_ORDER_initial_check_suppresses_notification():
    change = detect_availability_change(None, "available")

    assert change.previous_status is None
    assert change.current_status == "available"
    assert change.should_notify is False
    assert next_status_after_check(change.current_status) == "available"


def test_change_detector_RIGHT_no_slots_to_available_triggers_notify():
    change = detect_availability_change("no_slots", "available")

    assert change.previous_status == "no_slots"
    assert change.current_status == "available"
    assert change.should_notify is True
