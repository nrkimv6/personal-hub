"""POPPLY notification message builder."""

from app.modules.availability.types import AvailabilitySlot


def build_popply_slot_message(name: str, date: str, slots: list[AvailabilitySlot]) -> str:
    lines = [f"POPPLY 예약 가능: {name} ({date})"]
    for slot in slots:
        label = slot.label or "시간 미확인"
        lines.append(f"- {label}: {slot.available_count}명")
    return "\n".join(lines)
