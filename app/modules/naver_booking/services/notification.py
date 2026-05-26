"""Notification message builders for Naver booking monitoring."""

from typing import List, Optional


def build_naver_slot_message(
    label: str,
    url: Optional[str],
    new_slot_times: List[str],
    all_slots: List[str],
    auto_booking_enabled: bool = False,
) -> str:
    """Build the user-facing message for newly detected Naver booking slots."""
    lines = [
        "🔔 새 예약 슬롯 감지",
        label,
        f"새 시간: {', '.join(new_slot_times)}",
        f"전체 슬롯: {len(all_slots)}개",
    ]
    if url:
        lines.append(url)
    lines.append(f"자동 예약: {'활성' if auto_booking_enabled else '비활성'}")
    return "\n".join(lines)
