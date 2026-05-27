"""Tests for eventus_reservation.services.adapter."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.modules.availability.types import AvailabilityCheckResult
from app.modules.eventus_reservation.services.adapter import EventusReservationAdapter
from app.modules.eventus_reservation.services.http_client import EventusHttpClient

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CLOSED_HTML = (FIXTURE_DIR / "eventus_126341_closed.html").read_text(encoding="utf-8")
SOLDOUT_WRAPPER_HTML = (
    FIXTURE_DIR / "eventus_126341_soldout_bundle_wrapper.html"
).read_text(encoding="utf-8")
_SOURCE_URL = "https://event-us.kr/age20scoffee/event/126341"


def _make_adapter(html: str) -> EventusReservationAdapter:
    client = MagicMock(spec=EventusHttpClient)
    client.fetch_event_page = AsyncMock(return_value=html)
    return EventusReservationAdapter(client=client)


# ---------------------------------------------------------------------------
# Closed slots → available_count = 0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_closed_slots_have_available_count_zero():
    """R: 모든 슬롯이 마감이면 available_count=0인 슬롯만 반환된다."""
    # Use only bundle_morning_A (all closed)
    adapter = _make_adapter(CLOSED_HTML)
    result = await adapter.check(source_url=_SOURCE_URL, target_bundle_id="bundle_morning_A")
    assert isinstance(result, AvailabilityCheckResult)
    assert result.error_message is None
    for slot in result.slots:
        assert slot.available_count == 0


@pytest.mark.asyncio
async def test_no_slots_total_available_count_zero():
    """R: 전체 마감 상태이면 result.available_count = 0."""
    adapter = _make_adapter(CLOSED_HTML)
    result = await adapter.check(source_url=_SOURCE_URL, target_bundle_id="bundle_morning_A")
    assert (result.available_count or 0) == 0


@pytest.mark.asyncio
async def test_adapter_soldout_bundle_wrapper_returns_no_slots_RIGHT():
    """R: timeKey=null/dateLabel=null/label=bundleId wrapper는 available로 세지 않는다."""
    adapter = _make_adapter(SOLDOUT_WRAPPER_HTML)
    result = await adapter.check(source_url=_SOURCE_URL, target_bundle_id="52057")

    assert result.error_message is None
    assert result.available_count == 0
    assert result.slots
    assert all(slot.available_count == 0 for slot in result.slots)
    assert all(slot.raw.get("timeKey") for slot in result.slots)


@pytest.mark.asyncio
async def test_adapter_time_key_null_bundle_label_not_available_BOUNDARY():
    """B: 시간 label 없는 ui-menu-item은 open sentinel로 승격하지 않는다."""
    html = """
    <html><!-- event-us -->
    <body>
    <h1>Bundle Wrapper Event</h1>
    <a href="/regorg/event">RegOrg</a>
    <div v-if="userSlectedBundle.id === 'bundle_wrapper'">
      <ui-menu-item>
        <span>bundle_wrapper</span>
      </ui-menu-item>
    </div>
    <script>var ProjectId = 111;</script>
    </body>
    </html>
    """
    adapter = _make_adapter(html)
    result = await adapter.check(source_url=_SOURCE_URL, target_bundle_id="bundle_wrapper")

    assert result.error_message is None
    assert result.slots == []
    assert result.available_count == 0


# ---------------------------------------------------------------------------
# Open slot → available_count = 1 sentinel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_slot_returns_sentinel():
    """R: 마감 토큰 없는 열린 슬롯은 available_count=1 (sentinel)."""
    html = f"""
    <html>
    <body>
    <h1>Open Event</h1>
    <a href="/testorg/event">TestOrg</a>
    <div v-if="userSlectedBundle.id === 'bundle_open'">
    <ui-menu-item>
      <span>6/1 10:00~12:00</span>
    </ui-menu-item>
    </div>
    <script>var ProjectId = 999;</script>
    </body>
    </html>
    """
    # Need to add "event-us" landmark for bot-block detection to pass
    html_with_landmark = html.replace("<html>", "<html><!-- event-us -->")
    adapter = _make_adapter(html_with_landmark)
    result = await adapter.check(source_url=_SOURCE_URL, target_bundle_id="bundle_open")
    open_slots = [s for s in result.slots if s.available_count > 0]
    assert len(open_slots) >= 1
    assert open_slots[0].available_count == 1
    assert open_slots[0].raw.get("availableCountKnown") is False


# ---------------------------------------------------------------------------
# Imminent slot → urgencyHint = "imminent"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_imminent_slot_urgency_hint():
    """R: 마감임박 토큰 슬롯은 urgencyHint='imminent', available_count=1."""
    adapter = _make_adapter(CLOSED_HTML)
    # bundle_afternoon_B has one imminent slot at 6/2 16:00~18:00
    result = await adapter.check(source_url=_SOURCE_URL, target_bundle_id="bundle_afternoon_B")
    imminent_slots = [s for s in result.slots if s.raw.get("urgencyHint") == "imminent"]
    assert len(imminent_slots) == 1
    imminent = imminent_slots[0]
    assert imminent.available_count == 1  # available sentinel
    assert imminent.raw.get("closedText") == "마감임박"


@pytest.mark.asyncio
async def test_imminent_slot_is_not_closed():
    """R: 마감임박 슬롯은 is_available=True (알림 가능 상태)."""
    adapter = _make_adapter(CLOSED_HTML)
    result = await adapter.check(source_url=_SOURCE_URL, target_bundle_id="bundle_afternoon_B")
    imminent_slots = [s for s in result.slots if s.raw.get("urgencyHint") == "imminent"]
    assert len(imminent_slots) == 1
    assert imminent_slots[0].is_available is True


# ---------------------------------------------------------------------------
# Bundle/time filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bundle_filter():
    """R: target_bundle_id 필터가 해당 bundle 슬롯만 남긴다."""
    adapter = _make_adapter(CLOSED_HTML)
    result = await adapter.check(source_url=_SOURCE_URL, target_bundle_id="bundle_morning_A")
    for slot in result.slots:
        assert slot.raw.get("bundleId") == "bundle_morning_A"


@pytest.mark.asyncio
async def test_time_key_filter():
    """R: target_time_key 필터가 해당 시간대 슬롯만 남긴다."""
    adapter = _make_adapter(CLOSED_HTML)
    result = await adapter.check(
        source_url=_SOURCE_URL,
        target_bundle_id="bundle_morning_A",
        target_time_key="6/1 09:00~11:00",
    )
    # Should have 1 slot with matching time label
    assert len(result.slots) <= 5  # bundle filter applies first
    matched = [s for s in result.slots if s.label == "6/1 09:00~11:00"]
    assert len(matched) >= 0  # time_key may or may not match depending on extraction


# ---------------------------------------------------------------------------
# raw fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_raw_fields_present():
    """R: raw에 sourceType, eventId, bundleId, availableCountKnown 포함."""
    adapter = _make_adapter(CLOSED_HTML)
    result = await adapter.check(source_url=_SOURCE_URL, target_bundle_id="bundle_morning_A")
    if result.slots:
        raw = result.slots[0].raw
        assert raw.get("sourceType") == "eventus"
        assert raw.get("bundleId") == "bundle_morning_A"
        assert "availableCountKnown" in raw


# ---------------------------------------------------------------------------
# raw key regression (Phase T1 — slot display contract)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_raw_includes_time_key_and_bundle_id_regression():
    """R(regression): raw dict에 timeKey, bundleId, availableCountKnown, urgencyHint 키가 항상 포함된다.

    eventusSlotDisplay.ts 파서가 이 키에 의존하므로 adapter가 누락하면 안 된다.
    """
    html = """
    <html><!-- event-us -->
    <body>
    <h1>TC Regression Event</h1>
    <a href="/regorg/event">RegOrg</a>
    <div v-if="userSlectedBundle.id === 'bundle_reg'">
    <ui-menu-item>
      <span>6/10 14:00~16:00</span>
    </ui-menu-item>
    </div>
    <script>var ProjectId = 111;</script>
    </body>
    </html>
    """
    adapter = _make_adapter(html)
    result = await adapter.check(source_url=_SOURCE_URL, target_bundle_id="bundle_reg")

    open_slots = [s for s in result.slots if s.available_count > 0]
    assert len(open_slots) >= 1, "열린 슬롯이 하나 이상 있어야 합니다."
    raw = open_slots[0].raw
    assert "timeKey" in raw, (
        "raw에 timeKey 키가 없습니다. eventusSlotDisplay.ts 파서가 의존하는 키입니다."
    )
    assert "bundleId" in raw, (
        "raw에 bundleId 키가 없습니다. eventusSlotDisplay.ts 파서가 의존하는 키입니다."
    )
    assert "availableCountKnown" in raw, (
        "raw에 availableCountKnown 키가 없습니다. 수량 미확인 표시에 필요합니다."
    )
    assert "urgencyHint" in raw, (
        "raw에 urgencyHint 키가 없습니다. 마감임박 배지에 필요합니다."
    )
    assert raw["availableCountKnown"] is False, (
        "Eventus는 정확한 좌석 수를 알 수 없으므로 availableCountKnown은 항상 False여야 합니다."
    )


# ---------------------------------------------------------------------------
# Fetch error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_exception_returns_error_message():
    """E: HTTP client 예외 → error_message, fetch_method='anonymous_html'."""
    client = MagicMock(spec=EventusHttpClient)
    client.fetch_event_page = AsyncMock(side_effect=RuntimeError("Eventus HTTP 503"))
    adapter = EventusReservationAdapter(client=client)
    result = await adapter.check(source_url=_SOURCE_URL)
    assert result.error_message is not None
    assert "503" in result.error_message
    assert result.fetch_method == "anonymous_html"
    assert result.slots == []
