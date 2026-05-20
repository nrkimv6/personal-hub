from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse


APOLLO_STATE_MARKER = "window.__APOLLO_STATE__"
BOOKING_DOMAINS = {
    "booking.naver.com",
    "m.booking.naver.com",
}
EXTERNAL_RESERVATION_DOMAINS = BOOKING_DOMAINS | {
    "form.naver.com",
    "naver.me",
}
BOOKING_ROOT_CONFIG_URLS = {
    "https://booking.naver.com",
    "https://booking.naver.com/",
    "https://m.booking.naver.com",
    "https://m.booking.naver.com/",
}
RESERVATION_LABELS = {
    "예약",
    "예약하기",
    "방문 예약",
    "사전 예약",
}
PLACE_ID_RE = re.compile(
    r"(?:/place/|/popupstore/|/entry/place/)(?P<place_id>\d+)(?:[/?#]|$)"
)


@dataclass
class ReservationSignal:
    kind: str
    path: str
    value: str | int | bool | None = None
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReservationState:
    available: bool = False
    signals: list[ReservationSignal] = field(default_factory=list)
    booking_business_id: str | None = None
    booking_url: str | None = None
    ticket_count: int = 0
    concrete_links: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "signals": [signal.to_dict() for signal in self.signals],
            "booking_business_id": self.booking_business_id,
            "booking_url": self.booking_url,
            "ticket_count": self.ticket_count,
            "concrete_links": list(self.concrete_links),
        }


def _is_non_empty(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _extract_apollo_state(html_or_state: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(html_or_state, dict):
        return html_or_state
    if not isinstance(html_or_state, str) or APOLLO_STATE_MARKER not in html_or_state:
        return {}

    marker_index = html_or_state.find(APOLLO_STATE_MARKER)
    equals_index = html_or_state.find("=", marker_index)
    if equals_index < 0:
        return {}

    payload = html_or_state[equals_index + 1 :].lstrip()
    try:
        state, _offset = json.JSONDecoder().raw_decode(payload)
    except json.JSONDecodeError:
        return {}
    return state if isinstance(state, dict) else {}


def _iter_place_details(apollo_state: dict[str, Any]) -> list[dict[str, Any]]:
    root_query = apollo_state.get("ROOT_QUERY")
    root_query = root_query if isinstance(root_query, dict) else {}

    details: list[dict[str, Any]] = []
    for key, value in root_query.items():
        if key.startswith("placeDetail(") and isinstance(value, dict):
            details.append(value)

    for value in apollo_state.values():
        if not isinstance(value, dict):
            continue
        if value.get("__typename") == "PlaceDetail" and value not in details:
            details.append(value)
    return details


def _walk_dicts(node: Any, path: str = "state") -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        found.append((path, node))
        for key, value in node.items():
            found.extend(_walk_dicts(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_walk_dicts(value, f"{path}[{index}]"))
    return found


def _normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def extract_place_id(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if raw.isdigit():
        return raw
    match = PLACE_ID_RE.search(raw)
    if match:
        return match.group("place_id")
    return None


def build_place_reservation_url(place_id: str) -> str:
    return f"https://m.place.naver.com/popupstore/{place_id}/home"


def _host_matches(host: str, domains: set[str]) -> bool:
    host = host.lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _is_concrete_booking_url(url: str) -> bool:
    if not _is_non_empty(url):
        return False
    stripped = url.strip()
    if stripped in BOOKING_ROOT_CONFIG_URLS:
        return False

    parsed = urlparse(stripped)
    if not parsed.scheme.startswith("http") or not parsed.netloc:
        return False
    if not _host_matches(parsed.netloc, EXTERNAL_RESERVATION_DOMAINS):
        return False
    if parsed.netloc.lower().endswith("booking.naver.com"):
        return parsed.path not in {"", "/"}
    return True


def _append_signal_once(state: ReservationState, signal: ReservationSignal) -> None:
    for existing in state.signals:
        if existing.kind == signal.kind and existing.path == signal.path and existing.url == signal.url:
            return
    state.signals.append(signal)


def _record_link(state: ReservationState, url: str) -> None:
    normalized = _normalize_url(url)
    if normalized not in {_normalize_url(link) for link in state.concrete_links}:
        state.concrete_links.append(url)


def _apply_naver_booking(
    state: ReservationState,
    naver_booking: dict[str, Any],
    path: str,
) -> None:
    business_id = naver_booking.get("bookingBusinessId")
    booking_url = naver_booking.get("naverBookingUrl")
    hub_url = naver_booking.get("naverBookingHubUrl")

    if _is_non_empty(business_id):
        state.booking_business_id = str(business_id).strip()
        _append_signal_once(
            state,
            ReservationSignal(
                kind="booking_business_id",
                path=f"{path}.bookingBusinessId",
                value=state.booking_business_id,
            ),
        )

    for key, value in [
        ("naverBookingUrl", booking_url),
        ("naverBookingHubUrl", hub_url),
    ]:
        if not _is_non_empty(value):
            continue
        text = str(value).strip()
        state.booking_url = state.booking_url or text
        _append_signal_once(
            state,
            ReservationSignal(
                kind="booking_url",
                path=f"{path}.{key}",
                value=text,
                url=text,
            ),
        )
        if _is_concrete_booking_url(text):
            _record_link(state, text)


def _apply_tickets(state: ReservationState, tickets: dict[str, Any], path: str) -> None:
    total = tickets.get("total")
    items = tickets.get("items")
    more_booking_url = tickets.get("moreBookingUrl")

    if isinstance(total, int) and total > 0:
        state.ticket_count = max(state.ticket_count, total)
        _append_signal_once(
            state,
            ReservationSignal(kind="ticket_total", path=f"{path}.total", value=total),
        )

    if isinstance(items, list) and items:
        state.ticket_count = max(state.ticket_count, len(items))
        _append_signal_once(
            state,
            ReservationSignal(kind="ticket_items", path=f"{path}.items", value=len(items)),
        )
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            booking_url = item.get("bookingUrl")
            if _is_non_empty(booking_url):
                text = str(booking_url).strip()
                _append_signal_once(
                    state,
                    ReservationSignal(
                        kind="ticket_booking_url",
                        path=f"{path}.items[{index}].bookingUrl",
                        value=text,
                        url=text,
                    ),
                )
                if _is_concrete_booking_url(text):
                    _record_link(state, text)

    if _is_non_empty(more_booking_url):
        text = str(more_booking_url).strip()
        _append_signal_once(
            state,
            ReservationSignal(
                kind="more_booking_url",
                path=f"{path}.moreBookingUrl",
                value=text,
                url=text,
            ),
        )
        if _is_concrete_booking_url(text):
            _record_link(state, text)


def _iter_rendered_links(rendered_dom: Any) -> list[dict[str, Any]]:
    if rendered_dom is None:
        return []
    if isinstance(rendered_dom, list):
        return [item for item in rendered_dom if isinstance(item, dict)]
    if isinstance(rendered_dom, str):
        links: list[dict[str, Any]] = []
        for match in re.finditer(r'href=["\']([^"\']+)["\']', rendered_dom, flags=re.IGNORECASE):
            links.append({"href": match.group(1), "visible": True, "text": ""})
        return links
    return []


def _apply_rendered_dom(state: ReservationState, rendered_dom: Any) -> None:
    has_apollo_true_signal = any(
        signal.kind
        in {
            "booking_business_id",
            "booking_url",
            "ticket_total",
            "ticket_items",
            "ticket_booking_url",
            "more_booking_url",
        }
        for signal in state.signals
    )

    for index, link in enumerate(_iter_rendered_links(rendered_dom)):
        if link.get("visible") is False:
            continue
        href = str(link.get("href") or "").strip()
        label = str(link.get("text") or link.get("label") or "").strip()

        if _is_concrete_booking_url(href):
            _record_link(state, href)
            _append_signal_once(
                state,
                ReservationSignal(
                    kind="concrete_booking_link",
                    path=f"rendered_dom[{index}].href",
                    value=label or href,
                    url=href,
                ),
            )
            continue

        if label in RESERVATION_LABELS and has_apollo_true_signal:
            _append_signal_once(
                state,
                ReservationSignal(
                    kind="reservation_cta_label",
                    path=f"rendered_dom[{index}].text",
                    value=label,
                    url=href or None,
                ),
            )


def extract_place_reservation_state(
    html_or_state: str | dict[str, Any] | None,
    rendered_dom: Any = None,
) -> ReservationState:
    apollo_state = _extract_apollo_state(html_or_state)
    state = ReservationState()

    for index, detail in enumerate(_iter_place_details(apollo_state)):
        naver_booking = detail.get("naverBooking")
        if isinstance(naver_booking, dict):
            _apply_naver_booking(state, naver_booking, f"placeDetail[{index}].naverBooking")

        tickets = detail.get("tickets")
        if isinstance(tickets, dict):
            _apply_tickets(state, tickets, f"placeDetail[{index}].tickets")

    for path, value in _walk_dicts(apollo_state):
        if value.get("__typename") == "TicketItemsResult":
            _apply_tickets(state, value, path)

    _apply_rendered_dom(state, rendered_dom)
    state.available = any(
        signal.kind
        in {
            "booking_business_id",
            "booking_url",
            "ticket_total",
            "ticket_items",
            "ticket_booking_url",
            "more_booking_url",
            "concrete_booking_link",
            "reservation_cta_label",
        }
        for signal in state.signals
    )
    return state

