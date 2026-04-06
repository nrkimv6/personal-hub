from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

APOLLO_STATE_PATTERN = re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{[^<]*\})")


@dataclass
class PopupItem:
    item_key: str
    popup_id: str | None
    title: str
    place_name: str | None
    start_date: str | None
    end_date: str | None
    status: str | None
    reservation_url: str | None
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PopupParseResult:
    has_apollo_state: bool
    parse_error: str | None
    root_query_key_count: int
    root_query_popup_keys: list[str]
    items: list[PopupItem]


def _first_non_empty(value: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        current = value.get(key)
        if current is None:
            continue
        text = str(current).strip()
        if text:
            return text
    return None


def _collect_refs(node: Any, out: set[str]) -> None:
    if isinstance(node, str):
        if ":" in node:
            out.add(node)
        return
    if isinstance(node, list):
        for item in node:
            _collect_refs(item, out)
        return
    if isinstance(node, dict):
        for value in node.values():
            _collect_refs(value, out)


def _is_popup_entity(entity_key: str, entity: dict[str, Any]) -> bool:
    key_lower = entity_key.lower()
    typename = str(entity.get("__typename", "")).lower()

    if "popup" in key_lower or "popup" in typename:
        return True

    popup_like_fields = [
        "popupId",
        "popupStoreId",
        "popupName",
        "bookingUrl",
        "reservationUrl",
    ]
    return any(field in entity for field in popup_like_fields)


def _build_item_key(
    popup_id: str | None,
    title: str,
    place_name: str | None,
    start_date: str | None,
    end_date: str | None,
    reservation_url: str | None,
) -> str:
    if popup_id:
        return f"id:{popup_id}"
    if reservation_url:
        return f"url:{reservation_url}"
    source = "|".join(
        [
            title or "",
            place_name or "",
            start_date or "",
            end_date or "",
        ]
    )
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]
    return f"hash:{digest}"


def _normalize_popup_entity(entity: dict[str, Any]) -> PopupItem:
    popup_id = _first_non_empty(
        entity,
        ["popupId", "popupStoreId", "id", "storeId", "placeId"],
    )
    title = (
        _first_non_empty(entity, ["popupName", "title", "name", "storeName"])
        or "(untitled popup)"
    )
    place_name = _first_non_empty(
        entity,
        ["placeName", "venueName", "address", "roadAddress"],
    )
    start_date = _first_non_empty(
        entity,
        ["startDate", "startDateTime", "openDate", "startAt"],
    )
    end_date = _first_non_empty(
        entity,
        ["endDate", "endDateTime", "closeDate", "endAt"],
    )
    status = _first_non_empty(entity, ["status", "state", "progressStatus"])
    reservation_url = _first_non_empty(
        entity,
        ["bookingUrl", "reservationUrl", "url", "link"],
    )
    item_key = _build_item_key(
        popup_id=popup_id,
        title=title,
        place_name=place_name,
        start_date=start_date,
        end_date=end_date,
        reservation_url=reservation_url,
    )
    return PopupItem(
        item_key=item_key,
        popup_id=popup_id,
        title=title,
        place_name=place_name,
        start_date=start_date,
        end_date=end_date,
        status=status,
        reservation_url=reservation_url,
        raw=entity,
    )


def parse_popup_items_from_html(html: str) -> PopupParseResult:
    apollo_match = APOLLO_STATE_PATTERN.search(html)
    if not apollo_match:
        return PopupParseResult(
            has_apollo_state=False,
            parse_error="apollo_state_not_found",
            root_query_key_count=0,
            root_query_popup_keys=[],
            items=[],
        )

    try:
        apollo_state = json.loads(apollo_match.group(1))
    except json.JSONDecodeError as exc:
        return PopupParseResult(
            has_apollo_state=True,
            parse_error=f"apollo_json_decode_error: {exc}",
            root_query_key_count=0,
            root_query_popup_keys=[],
            items=[],
        )

    root_query = apollo_state.get("ROOT_QUERY")
    root_query = root_query if isinstance(root_query, dict) else {}
    root_query_keys = sorted(root_query.keys())
    root_query_popup_keys = [
        key
        for key in root_query_keys
        if "popup" in key.lower() or "store" in key.lower()
    ]

    refs: set[str] = set()
    _collect_refs(root_query, refs)

    popup_entities: list[dict[str, Any]] = []
    for ref in sorted(refs):
        entity = apollo_state.get(ref)
        if not isinstance(entity, dict):
            continue
        if _is_popup_entity(ref, entity):
            popup_entities.append(entity)

    if not popup_entities:
        for key, value in apollo_state.items():
            if key == "ROOT_QUERY" or not isinstance(value, dict):
                continue
            if _is_popup_entity(key, value):
                popup_entities.append(value)

    item_map: dict[str, PopupItem] = {}
    for entity in popup_entities:
        item = _normalize_popup_entity(entity)
        item_map[item.item_key] = item

    return PopupParseResult(
        has_apollo_state=True,
        parse_error=None,
        root_query_key_count=len(root_query_keys),
        root_query_popup_keys=root_query_popup_keys[:50],
        items=list(item_map.values()),
    )

