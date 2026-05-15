"""Detect availability transitions without notifying on the first check."""

from dataclasses import dataclass
from typing import Optional

from app.modules.availability.types import AvailabilityStatus


@dataclass(frozen=True)
class AvailabilityChange:
    previous_status: Optional[AvailabilityStatus]
    current_status: AvailabilityStatus
    should_notify: bool


def detect_availability_change(
    previous_status: Optional[AvailabilityStatus],
    current_status: AvailabilityStatus,
) -> AvailabilityChange:
    if previous_status is None:
        return AvailabilityChange(
            previous_status=None,
            current_status=current_status,
            should_notify=False,
        )
    return AvailabilityChange(
        previous_status=previous_status,
        current_status=current_status,
        should_notify=previous_status != "available" and current_status == "available",
    )


def next_status_after_check(current_status: AvailabilityStatus) -> AvailabilityStatus:
    return current_status
