"""Eventus event page one-shot analyzer.

Fetches the event page once and extracts:
- title, organizer_slug, channel_name, event_id
- bundle IDs and per-slot status
- closed_token_counts

Bot-block detection: if the returned HTML is shorter than _BOT_BLOCK_THRESHOLD
bytes or does not contain expected landmark tokens, the result carries
error_code="bot_block_suspected".

Playwright request fallback is intentionally NOT wired in this module — it is
a separate surface concern (T5 live read-back will determine if it is needed).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.modules.eventus_reservation.services.event_resolver import (
    EventIdResolverError,
    EventusEventResolver,
    ResolvedEventusUrl,
)
from app.modules.eventus_reservation.services.html_parser import (
    EventusMeta,
    EventusSlot,
    parse_event_meta,
)
from app.modules.eventus_reservation.services.http_client import EventusHttpClient
from app.modules.eventus_reservation.utils.url_parser import EventusInput

logger = logging.getLogger(__name__)

# HTML shorter than this after fetch → suspected bot block
_BOT_BLOCK_THRESHOLD = 2_000
# Landmark that must appear in a real event page
_LANDMARK_TOKEN = "event-us"


@dataclass
class EventusAnalyzeResult:
    event_id: Optional[str]
    source_url: Optional[str]
    organizer_slug: Optional[str]
    channel_name: Optional[str]
    title: Optional[str]
    bundles: list[str] = field(default_factory=list)
    slots: list[EventusSlot] = field(default_factory=list)
    closed_token_counts: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    fetch_method: str = "anonymous_html"
    raw_html_length: int = 0


class EventusAnalyzer:
    """One-shot analyzer: fetch event page and extract meta/bundle/time candidates."""

    def __init__(
        self,
        http_client: Optional[EventusHttpClient] = None,
        resolver: Optional[EventusEventResolver] = None,
    ):
        self._client = http_client or EventusHttpClient()
        self._resolver = resolver or EventusEventResolver()

    async def analyze(self, inp: EventusInput) -> EventusAnalyzeResult:
        """Fetch event page and return EventusAnalyzeResult.

        Error codes:
          - ``event_id_resolver_error``: bare event_id with no organizer slug.
          - ``fetch_error``: HTTP client raised an exception.
          - ``bot_block_suspected``: HTML too short or missing landmark token.
        """
        # Resolve source URL
        try:
            resolved: ResolvedEventusUrl = self._resolver.resolve(inp)
        except EventIdResolverError as exc:
            return EventusAnalyzeResult(
                event_id=inp.event_id,
                source_url=None,
                organizer_slug=None,
                channel_name=None,
                title=None,
                error_code="event_id_resolver_error",
                error_message=str(exc),
            )

        # Fetch
        try:
            html = await self._client.fetch_event_page(resolved.source_url)
        except Exception as exc:
            return EventusAnalyzeResult(
                event_id=resolved.event_id,
                source_url=resolved.source_url,
                organizer_slug=resolved.organizer_slug,
                channel_name=None,
                title=None,
                error_code="fetch_error",
                error_message=str(exc),
                fetch_method="anonymous_html",
            )

        html_len = len(html)

        # Bot-block detection
        if html_len < _BOT_BLOCK_THRESHOLD or _LANDMARK_TOKEN not in html.lower():
            return EventusAnalyzeResult(
                event_id=resolved.event_id,
                source_url=resolved.source_url,
                organizer_slug=resolved.organizer_slug,
                channel_name=None,
                title=None,
                error_code="bot_block_suspected",
                error_message=(
                    f"HTML length {html_len} < {_BOT_BLOCK_THRESHOLD} or "
                    f"landmark '{_LANDMARK_TOKEN}' missing — possible bot block"
                ),
                fetch_method="anonymous_html",
                raw_html_length=html_len,
            )

        # Parse
        meta: EventusMeta = parse_event_meta(
            html,
            source_url=resolved.source_url,
            organizer_slug=resolved.organizer_slug,
            event_id_hint=resolved.event_id,
        )

        closed_count = sum(1 for s in meta.slots if s.is_closed)

        return EventusAnalyzeResult(
            event_id=meta.event_id or resolved.event_id,
            source_url=resolved.source_url,
            organizer_slug=meta.organizer_slug or resolved.organizer_slug,
            channel_name=meta.channel_name,
            title=meta.title,
            bundles=meta.bundle_ids,
            slots=meta.slots,
            closed_token_counts=closed_count,
            fetch_method="anonymous_html",
            raw_html_length=html_len,
        )
