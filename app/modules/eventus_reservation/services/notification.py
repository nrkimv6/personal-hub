"""Eventus notification message builder."""

from app.modules.availability.types import AvailabilitySlot


def build_eventus_slot_message(
    name: str,
    date: str,
    slots: list[AvailabilitySlot],
) -> str:
    """Build notification message for newly available Eventus slots.

    Args:
        name: Event/item display name.
        date: Schedule date string.
        slots: Available AvailabilitySlot list (is_available == True).

    Returns:
        Formatted notification string.
    """
    lines = [f"이벤터스 잔여석 감지: {name} ({date})"]
    for slot in slots:
        label = slot.label or "시간 미확인"
        urgency = slot.raw.get("urgencyHint")
        suffix = " (마감임박)" if urgency == "imminent" else ""
        lines.append(f"- {label}: 잔여 있음{suffix}")
    return "\n".join(lines)
