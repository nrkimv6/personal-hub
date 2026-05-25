"""Eventus event URL parser and input normalizer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_EVENTUS_URL_RE = re.compile(
    r"^https?://event-us\.kr/(?P<organizer>[^/?#]+)/event/(?P<event_id>\d+)/?$"
)


@dataclass
class EventusEventUrl:
    organizer_slug: str
    event_id: str
    source_url: str


@dataclass
class EventusInput:
    event_id: str
    source_url: Optional[str] = None
    organizer_slug: Optional[str] = None


def parse_eventus_event_url(url: str) -> EventusEventUrl:
    """Parse https://event-us.kr/{organizer}/event/{event_id} → EventusEventUrl.

    Raises:
        ValueError: If scheme/host/path/event_id is missing or malformed.
    """
    if not url or not url.strip():
        raise ValueError("Invalid Eventus event URL")
    m = _EVENTUS_URL_RE.match(url.strip())
    if not m:
        raise ValueError("Invalid Eventus event URL")
    return EventusEventUrl(
        organizer_slug=m.group("organizer"),
        event_id=m.group("event_id"),
        source_url=url.strip(),
    )


def normalize_eventus_input(value: str) -> EventusInput:
    """Normalize event_id (digit-only) or full URL into EventusInput.

    If ``value`` is a digit-only string, returns EventusInput with only event_id set
    (source_url=None) — callers must supply organizer_slug or full URL later.
    If ``value`` is a full URL, parses and returns EventusInput with all fields.
    """
    value = value.strip()
    if not value:
        raise ValueError("Invalid Eventus event URL")
    if value.isdigit():
        return EventusInput(event_id=value)
    parsed = parse_eventus_event_url(value)
    return EventusInput(
        event_id=parsed.event_id,
        source_url=parsed.source_url,
        organizer_slug=parsed.organizer_slug,
    )
