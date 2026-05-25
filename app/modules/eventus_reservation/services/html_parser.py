"""Eventus HTML page parser.

Parses server-rendered Vue HTML from event-us.kr to extract:
- Event title (<h1>)
- Organizer slug / channel name (anchor href pattern)
- Event ID (ProjectId JS var or URL hint)
- Bundle IDs (v-if="userSlectedBundle.id === '{bundle_id}'" pattern)
- Slots per bundle (ui-menu-item blocks with disabled / text-danger-400 status)

Closed tokens: 모집마감, Application Closed, No Left Tickets
Imminent token: 마감임박  → urgency_hint="imminent"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Token sets
# ---------------------------------------------------------------------------
_CLOSED_TOKENS: frozenset[str] = frozenset(["모집마감", "Application Closed", "No Left Tickets"])
_IMMINENT_TOKENS: frozenset[str] = frozenset(["마감임박"])

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL | re.IGNORECASE)
# href="/{organizer}/event" anchor text (relative or absolute URL)
_CHANNEL_ANCHOR_RE = re.compile(
    r'href="[^"]*?/([^/?"#]+)/event[^"]*"\s*[^>]*>([^<]+)<',
    re.IGNORECASE,
)
# ProjectId variable in page JS
_PROJECT_ID_RE = re.compile(r"ProjectId\s*[=:]\s*[\"']?(\d+)[\"']?", re.IGNORECASE)
# v-if="userSlectedBundle.id === 'BUNDLE_ID'"  (note typo "Slected" is in source)
_BUNDLE_VIF_RE = re.compile(
    r"""v-if\s*=\s*["']userSlectedBundle\.id\s*===\s*['"]([^'"]+)['"]\s*["']""",
    re.IGNORECASE,
)
# Time label: M/D HH:MM~HH:MM (e.g. "6/1 09:00~11:00")
_TIME_LABEL_RE = re.compile(r"\d{1,2}/\d{1,2}\s+\d{2}:\d{2}~\d{2}:\d{2}")
# Danger status text
_DANGER_TEXT_RE = re.compile(
    r'class="[^"]*text-danger-400[^"]*"\s*[^>]*>([^<]+)<',
    re.IGNORECASE,
)
# disabled attribute
_DISABLED_ATTR_RE = re.compile(r"\bdisabled\b", re.IGNORECASE)
# Opening ui-menu-item tag
_MENU_OPEN_RE = re.compile(r"<ui-menu-item\b[^>]*>", re.IGNORECASE)
# Closing ui-menu-item tag
_MENU_CLOSE_STR = "</ui-menu-item>"
_MENU_CLOSE_RE = re.compile(r"</ui-menu-item>", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class EventusSlot:
    bundle_id: str
    time_label: Optional[str] = None
    date_label: Optional[str] = None
    is_closed: bool = False
    closed_text: Optional[str] = None
    urgency_hint: Optional[str] = None  # "imminent" | None
    raw_block: str = ""


@dataclass
class EventusMeta:
    event_id: Optional[str] = None
    source_url: Optional[str] = None
    organizer_slug: Optional[str] = None
    channel_name: Optional[str] = None
    title: Optional[str] = None
    slots: list[EventusSlot] = field(default_factory=list)
    bundle_ids: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _extract_title(html: str) -> Optional[str]:
    m = _H1_RE.search(html)
    if not m:
        return None
    return _strip_tags(m.group(1)) or None


def _extract_channel(
    html: str,
    fallback_slug: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Return (organizer_slug, channel_display_name)."""
    m = _CHANNEL_ANCHOR_RE.search(html)
    if m:
        return m.group(1).strip(), _strip_tags(m.group(2))
    return fallback_slug, None


def _extract_event_id_from_html(html: str, fallback: Optional[str] = None) -> Optional[str]:
    m = _PROJECT_ID_RE.search(html)
    if m:
        return m.group(1)
    return fallback


def _parse_slot_block(block: str, bundle_id: str) -> EventusSlot:
    """Parse a single ui-menu-item block into an EventusSlot."""
    closed_text: Optional[str] = None
    is_closed = False
    urgency_hint: Optional[str] = None

    # Check danger text first
    danger_m = _DANGER_TEXT_RE.search(block)
    if danger_m:
        raw_status = danger_m.group(1).strip()
        if raw_status in _CLOSED_TOKENS:
            is_closed = True
            closed_text = raw_status
        elif raw_status in _IMMINENT_TOKENS:
            urgency_hint = "imminent"
            closed_text = raw_status
        else:
            # Unknown status text — preserve but don't mark closed
            closed_text = raw_status

    # disabled attribute → closed
    if _DISABLED_ATTR_RE.search(block):
        is_closed = True

    # Time label
    time_m = _TIME_LABEL_RE.search(block)
    time_label = time_m.group(0) if time_m else None

    return EventusSlot(
        bundle_id=bundle_id,
        time_label=time_label,
        date_label=time_label,  # same field for eventus
        is_closed=is_closed,
        closed_text=closed_text,
        urgency_hint=urgency_hint,
        raw_block=block[:600],
    )


def _collect_bundle_positions(html: str) -> tuple[list[str], list[tuple[int, str]]]:
    """Return (bundle_ids_ordered, [(html_position, bundle_id)])."""
    seen: list[str] = []
    positions: list[tuple[int, str]] = []
    for m in _BUNDLE_VIF_RE.finditer(html):
        bid = m.group(1)
        if bid not in seen:
            seen.append(bid)
        positions.append((m.start(), bid))
    return seen, positions


def _nearest_bundle_id(
    pos: int,
    bundle_id_positions: list[tuple[int, str]],
    fallback: str = "",
) -> str:
    """Find the bundle_id whose v-if position is closest before `pos`."""
    best = fallback
    for p, bid in bundle_id_positions:
        if p <= pos:
            best = bid
    return best


def _extract_slots(html: str, bundle_ids: list[str], bundle_id_positions: list[tuple[int, str]]) -> list[EventusSlot]:
    """Extract EventusSlot list from ui-menu-item blocks in html."""
    slots: list[EventusSlot] = []
    close_positions = [m.start() for m in _MENU_CLOSE_RE.finditer(html)]

    for open_m in _MENU_OPEN_RE.finditer(html):
        open_start = open_m.start()
        open_end = open_m.end()
        # Find first close tag after open end
        close_pos = next((c for c in close_positions if c > open_end), None)
        if close_pos is not None:
            block = html[open_start : close_pos + len(_MENU_CLOSE_STR)]
        else:
            block = html[open_start : open_start + 1500]

        bundle_id = _nearest_bundle_id(open_start, bundle_id_positions, fallback=bundle_ids[0] if bundle_ids else "")
        slots.append(_parse_slot_block(block, bundle_id))

    return slots


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_event_meta(
    html: str,
    source_url: Optional[str] = None,
    organizer_slug: Optional[str] = None,
    event_id_hint: Optional[str] = None,
) -> EventusMeta:
    """Parse Eventus event page HTML into EventusMeta.

    Args:
        html: Raw HTML of the event page.
        source_url: Original fetch URL (stored for reference).
        organizer_slug: Hint from URL parser (used as fallback).
        event_id_hint: event_id from URL path (fallback if ProjectId not found).

    Returns:
        EventusMeta with extracted title, channel, bundle_ids, and slots.
    """
    meta = EventusMeta(source_url=source_url, organizer_slug=organizer_slug)

    meta.title = _extract_title(html)

    slug, channel_name = _extract_channel(html, fallback_slug=organizer_slug)
    meta.organizer_slug = slug or organizer_slug
    meta.channel_name = channel_name

    meta.event_id = _extract_event_id_from_html(html, fallback=event_id_hint)

    bundle_ids, bundle_id_positions = _collect_bundle_positions(html)
    meta.bundle_ids = bundle_ids

    if bundle_id_positions or _MENU_OPEN_RE.search(html):
        meta.slots = _extract_slots(html, bundle_ids, bundle_id_positions)
    else:
        meta.parse_errors.append("no bundle v-if or ui-menu-item found")

    return meta
