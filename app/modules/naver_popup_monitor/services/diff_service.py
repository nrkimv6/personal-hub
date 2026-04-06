from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class PopupDiffSummary:
    new_items: list[dict[str, Any]]
    updated_items: list[dict[str, Any]]
    removed_items: list[dict[str, Any]]

    @property
    def new_count(self) -> int:
        return len(self.new_items)

    @property
    def has_new(self) -> bool:
        return self.new_count > 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["new_count"] = self.new_count
        payload["has_new"] = self.has_new
        return payload


def _fingerprint(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("title"),
        item.get("place_name"),
        item.get("start_date"),
        item.get("end_date"),
        item.get("status"),
        item.get("reservation_url"),
    )


def calculate_popup_diff(
    previous_items: list[dict[str, Any]],
    current_items: list[dict[str, Any]],
) -> PopupDiffSummary:
    previous_map = {str(item.get("item_key")): item for item in previous_items if item.get("item_key")}
    current_map = {str(item.get("item_key")): item for item in current_items if item.get("item_key")}

    new_items = [item for key, item in current_map.items() if key not in previous_map]
    removed_items = [item for key, item in previous_map.items() if key not in current_map]

    updated_items: list[dict[str, Any]] = []
    for key in sorted(set(previous_map.keys()) & set(current_map.keys())):
        before = previous_map[key]
        after = current_map[key]
        if _fingerprint(before) != _fingerprint(after):
            updated_items.append(
                {
                    "item_key": key,
                    "before": before,
                    "after": after,
                }
            )

    return PopupDiffSummary(
        new_items=new_items,
        updated_items=updated_items,
        removed_items=removed_items,
    )

