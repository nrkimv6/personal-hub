"""Integration tests for eventus_reservation — real HTML parsing with fixture.

These tests use the real HTML fixture (no mocks for parser/adapter internals),
minimising mocks to the HTTP client only.  This verifies the full pipeline:
  fixture HTML → html_parser → adapter → AvailabilityCheckResult → state determination
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.availability.services.state import determine_availability_status
from app.modules.availability.types import AvailabilityCheckResult
from app.modules.eventus_reservation.services.adapter import EventusReservationAdapter
from app.modules.eventus_reservation.services.http_client import EventusHttpClient

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CLOSED_HTML = (FIXTURE_DIR / "eventus_126341_closed.html").read_text(encoding="utf-8")
_SOURCE_URL = "https://event-us.kr/age20scoffee/event/126341"


def _make_adapter(html: str) -> EventusReservationAdapter:
    client = MagicMock(spec=EventusHttpClient)
    client.fetch_event_page = AsyncMock(return_value=html)
    return EventusReservationAdapter(client=client)


# ---------------------------------------------------------------------------
# Full pipeline: closed HTML → all slots closed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_pipeline_closed_html_returns_no_slots_status():
    """T3: fixture HTML → adapter → state='no_slots' (bundle_morning_A 전부 마감)."""
    adapter = _make_adapter(CLOSED_HTML)
    result = await adapter.check(
        source_url=_SOURCE_URL,
        target_bundle_id="bundle_morning_A",
    )

    assert isinstance(result, AvailabilityCheckResult)
    assert result.error_message is None
    status = determine_availability_status(
        result.slots,
        available_count=result.available_count,
        error_message=result.error_message,
    )
    assert status == "no_slots"


@pytest.mark.asyncio
async def test_full_pipeline_imminent_slot_returns_available_status():
    """T3: 마감임박 슬롯(bundle_afternoon_B)은 state='available'."""
    adapter = _make_adapter(CLOSED_HTML)
    result = await adapter.check(
        source_url=_SOURCE_URL,
        target_bundle_id="bundle_afternoon_B",
    )

    assert result.error_message is None
    # At least one imminent slot → available
    imminent = [s for s in result.slots if s.raw.get("urgencyHint") == "imminent"]
    assert len(imminent) == 1

    status = determine_availability_status(
        result.slots,
        available_count=result.available_count,
        error_message=result.error_message,
    )
    assert status == "available"


@pytest.mark.asyncio
async def test_full_pipeline_raw_fields_populated():
    """T3: raw 필드에 sourceType/eventId/bundleId/availableCountKnown 포함."""
    adapter = _make_adapter(CLOSED_HTML)
    result = await adapter.check(
        source_url=_SOURCE_URL,
        target_bundle_id="bundle_morning_A",
    )

    assert len(result.slots) > 0
    slot = result.slots[0]
    assert slot.raw.get("sourceType") == "eventus"
    assert slot.raw.get("bundleId") == "bundle_morning_A"
    assert "availableCountKnown" in slot.raw
    assert "eventId" in slot.raw


@pytest.mark.asyncio
async def test_full_pipeline_all_bundles_no_filter_returns_all_slots():
    """T3: bundle 필터 없으면 모든 bundle 슬롯 반환 (15개)."""
    adapter = _make_adapter(CLOSED_HTML)
    result = await adapter.check(source_url=_SOURCE_URL)

    # fixture has 3 bundles × 5 slots = 15
    assert len(result.slots) == 15


@pytest.mark.asyncio
async def test_full_pipeline_fetch_error_returns_error_result():
    """T3: HTTP 오류 → error_message 포함, slots=[]."""
    client = MagicMock(spec=EventusHttpClient)
    client.fetch_event_page = AsyncMock(side_effect=RuntimeError("Eventus HTTP 503: url"))
    adapter = EventusReservationAdapter(client=client)

    result = await adapter.check(source_url=_SOURCE_URL)

    assert result.error_message is not None
    assert "503" in result.error_message
    assert result.slots == []
    status = determine_availability_status(
        result.slots,
        available_count=result.available_count,
        error_message=result.error_message,
    )
    assert status == "error"
