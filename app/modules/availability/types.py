"""Common availability result types shared by monitor adapters."""

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


AvailabilityStatus = Literal["available", "no_slots", "error"]


@dataclass
class AvailabilitySlot:
    """Normalized slot item produced by a source-specific adapter."""

    source_type: str
    available_count: int = 0
    label: Optional[str] = None
    slot_id: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        return self.available_count > 0


@dataclass
class AvailabilityCheckResult:
    """Normalized availability check result passed to common services."""

    source_type: str
    slots: list[AvailabilitySlot] = field(default_factory=list)
    available_count: Optional[int] = None
    raw: Any = None
    response_time_ms: Optional[float] = None
    fetch_method: Optional[str] = None
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        if self.available_count is None:
            self.available_count = sum(
                max(0, slot.available_count) for slot in self.slots
            )
