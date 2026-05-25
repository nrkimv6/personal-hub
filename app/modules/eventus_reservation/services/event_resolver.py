"""Eventus event_id → canonical source URL resolver.

event-us.kr requires the full path /{organizer}/event/{event_id} to access
an event page.  A bare event_id without the organizer slug cannot be resolved
server-side without a redirect/lookup API that is not publicly documented.

This resolver:
  - Returns immediately if source_url is already present (URL input path).
  - Raises EventIdResolverError for bare event_id-only inputs, directing the
    caller to supply the full URL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.modules.eventus_reservation.utils.url_parser import EventusInput

logger = logging.getLogger(__name__)


@dataclass
class ResolvedEventusUrl:
    event_id: str
    source_url: str
    organizer_slug: Optional[str] = None


class EventIdResolverError(ValueError):
    """Raised when event_id alone cannot be resolved to a canonical URL."""
    pass


class EventusEventResolver:
    """Resolve EventusInput to a canonical ResolvedEventusUrl."""

    def resolve(self, inp: EventusInput) -> ResolvedEventusUrl:
        """Return ResolvedEventusUrl from EventusInput.

        If ``inp.source_url`` is already populated (URL input path), return it
        immediately.  If only ``inp.event_id`` is provided, raise
        EventIdResolverError — event-us.kr needs /{organizer}/event/{id} and
        we cannot guess the organizer slug without a redirect API.

        Args:
            inp: Normalized EventusInput from url_parser.normalize_eventus_input.

        Returns:
            ResolvedEventusUrl with event_id, source_url, organizer_slug.

        Raises:
            EventIdResolverError: When source_url is absent and organizer_slug
                is unknown.
        """
        if inp.source_url:
            return ResolvedEventusUrl(
                event_id=inp.event_id,
                source_url=inp.source_url,
                organizer_slug=inp.organizer_slug,
            )

        raise EventIdResolverError(
            f"event_id '{inp.event_id}' 단독으로는 canonical URL을 확정할 수 없습니다. "
            f"전체 URL을 입력해 주세요: "
            f"https://event-us.kr/{{organizer}}/event/{inp.event_id}"
        )
