"""Eventus availability adapter.

Converts HTML parse result into a common AvailabilityCheckResult so that the
shared event writer and change detector can process it.

available_count sentinel rules:
  - Closed slot (closed token OR disabled attr):  available_count = 0
  - Imminent slot (마감임박 token):               available_count = 1, urgencyHint="imminent"
  - Open slot (no closed token, no disabled):     available_count = 1, availableCountKnown=false

The exact remaining count is never available from event-us.kr HTML, so 1 is
used as the "slot is open" sentinel value.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.modules.availability.types import AvailabilityCheckResult, AvailabilitySlot
from app.modules.eventus_reservation.services.html_parser import EventusSlot, parse_event_meta
from app.modules.eventus_reservation.services.http_client import EventusHttpClient

logger = logging.getLogger(__name__)


def _slot_to_availability(s: EventusSlot, event_id: Optional[str]) -> AvailabilitySlot:
    """Convert a single EventusSlot to an AvailabilitySlot."""
    is_slot_candidate = bool(s.time_label or s.date_label)
    if not is_slot_candidate:
        available_count = 0
        urgency_hint = None
    elif s.is_closed:
        available_count = 0
        urgency_hint = None
    elif s.urgency_hint == "imminent":
        available_count = 1  # available sentinel — limited seats
        urgency_hint = "imminent"
    else:
        available_count = 1  # available sentinel — count unknown
        urgency_hint = None

    return AvailabilitySlot(
        source_type="eventus",
        available_count=available_count,
        label=s.time_label or s.date_label or s.bundle_id,
        slot_id=f"{s.bundle_id}:{s.time_label or ''}",
        raw={
            "sourceType": "eventus",
            "eventId": event_id,
            "bundleId": s.bundle_id,
            "timeKey": s.time_label,
            "dateLabel": s.date_label,
            "closedText": s.closed_text,
            "availableCountKnown": False,
            "urgencyHint": urgency_hint,
            "slotCandidate": is_slot_candidate,
        },
    )


class EventusReservationAdapter:
    """Adapts Eventus HTML page state to AvailabilityCheckResult."""

    def __init__(self, client: Optional[EventusHttpClient] = None):
        self._client = client or EventusHttpClient()

    async def check(
        self,
        *,
        source_url: str,
        schedule_date: Optional[str] = None,
        target_bundle_id: Optional[str] = None,
        target_time_key: Optional[str] = None,
    ) -> AvailabilityCheckResult:
        """Fetch event page and return normalized AvailabilityCheckResult.

        Args:
            source_url: Full Eventus event page URL.
            schedule_date: Ignored currently (eventus uses bundle/time key directly).
            target_bundle_id: If set, restrict slots to this bundle.
            target_time_key: If set (and target_bundle_id matches), restrict to
                this time label.

        Returns:
            AvailabilityCheckResult with source_type="eventus".
        """
        started = datetime.now()

        try:
            html = await self._client.fetch_event_page(source_url)
        except Exception as exc:
            return AvailabilityCheckResult(
                source_type="eventus",
                raw=None,
                fetch_method="anonymous_html",
                response_time_ms=(datetime.now() - started).total_seconds() * 1000,
                error_message=str(exc),
            )

        meta = parse_event_meta(html, source_url=source_url)
        elapsed_ms = (datetime.now() - started).total_seconds() * 1000

        # Apply bundle/time filter
        candidate_slots: list[EventusSlot] = meta.slots
        if target_bundle_id:
            candidate_slots = [s for s in candidate_slots if s.bundle_id == target_bundle_id]
        if target_time_key and candidate_slots:
            filtered = [s for s in candidate_slots if s.time_label == target_time_key]
            if filtered:
                candidate_slots = filtered

        slots = [_slot_to_availability(s, meta.event_id) for s in candidate_slots]

        return AvailabilityCheckResult(
            source_type="eventus",
            slots=slots,
            raw={
                "event_id": meta.event_id,
                "bundle_ids": meta.bundle_ids,
                "slot_count": len(meta.slots),
                "filtered_slot_count": len(candidate_slots),
            },
            fetch_method="anonymous_html",
            response_time_ms=elapsed_ms,
        )
