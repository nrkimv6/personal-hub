"""Parse POPPLY reservation URLs."""

from dataclasses import dataclass
from urllib.parse import urlparse

from app.modules.popply_reservation.utils.hash_normalizer import (
    normalize_schedule_group_hash,
)


@dataclass(frozen=True)
class PopplyReservationUrl:
    store_id: str
    reservation_type: str
    source_hash: str
    target_schedule_group: str


def parse_popply_reservation_url(url: str) -> PopplyReservationUrl:
    parsed = urlparse((url or "").strip())
    parts = [part for part in parsed.path.split("/") if part]
    try:
        popup_idx = parts.index("popup")
        store_id = parts[popup_idx + 1]
        reservation_idx = parts.index("reservation")
        reservation_type = parts[reservation_idx + 1].upper()
        source_hash = parts[reservation_idx + 2]
    except (ValueError, IndexError) as exc:
        raise ValueError("Invalid POPPLY reservation URL") from exc
    if not store_id or not source_hash:
        raise ValueError("Invalid POPPLY reservation URL")
    return PopplyReservationUrl(
        store_id=store_id,
        reservation_type=reservation_type,
        source_hash=source_hash,
        target_schedule_group=normalize_schedule_group_hash(source_hash),
    )
