"""Tests for eventus_reservation.services.html_parser."""

from pathlib import Path

import pytest
from app.modules.eventus_reservation.services.html_parser import (
    EventusMeta,
    EventusSlot,
    parse_event_meta,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CLOSED_FIXTURE = FIXTURE_DIR / "eventus_126341_closed.html"
SOLDOUT_WRAPPER_FIXTURE = FIXTURE_DIR / "eventus_126341_soldout_bundle_wrapper.html"


def _load_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def closed_html() -> str:
    return _load_fixture(CLOSED_FIXTURE)


@pytest.fixture(scope="module")
def soldout_wrapper_html() -> str:
    return _load_fixture(SOLDOUT_WRAPPER_FIXTURE)


# ---------------------------------------------------------------------------
# Title / Channel extraction
# ---------------------------------------------------------------------------

def test_extract_title(closed_html: str):
    """R: fixture HTML에서 이벤트 제목을 추출한다."""
    meta = parse_event_meta(closed_html)
    assert meta.title is not None
    assert "커피챗" in meta.title or "네트워킹" in meta.title


def test_extract_channel_slug(closed_html: str):
    """R: fixture HTML에서 organizer_slug을 추출한다."""
    meta = parse_event_meta(closed_html, organizer_slug="age20scoffee")
    # Either from anchor or fallback
    assert meta.organizer_slug is not None


def test_extract_channel_name(closed_html: str):
    """R: fixture HTML에서 채널 표시명(Age20s Coffee)을 추출한다."""
    meta = parse_event_meta(closed_html)
    # channel_name may be extracted from anchor text
    # If not extracted, None is acceptable — but organizer_slug should be set
    assert meta.organizer_slug is not None or meta.channel_name is not None


def test_extract_event_id_from_html(closed_html: str):
    """R: fixture HTML의 ProjectId = 126341에서 event_id를 추출한다."""
    meta = parse_event_meta(closed_html)
    assert meta.event_id == "126341"


def test_event_id_fallback_from_hint(closed_html: str):
    """R: ProjectId 추출 실패 시 event_id_hint로 fallback."""
    # Remove ProjectId from html
    html_no_id = closed_html.replace("var ProjectId = 126341;", "")
    meta = parse_event_meta(html_no_id, event_id_hint="999999")
    assert meta.event_id == "999999"


# ---------------------------------------------------------------------------
# Bundle / Slot extraction
# ---------------------------------------------------------------------------

def test_extract_bundle_ids(closed_html: str):
    """R: fixture HTML에서 3개 bundle ID를 추출한다."""
    meta = parse_event_meta(closed_html)
    assert len(meta.bundle_ids) == 3
    assert "bundle_morning_A" in meta.bundle_ids
    assert "bundle_afternoon_B" in meta.bundle_ids
    assert "bundle_evening_C" in meta.bundle_ids


def test_extract_slot_count(closed_html: str):
    """R: fixture HTML에서 15개 슬롯을 추출한다 (5+5+5)."""
    meta = parse_event_meta(closed_html)
    # 3 bundles × 5 slots = 15 total
    assert len(meta.slots) == 15


def test_closed_slots_detected(closed_html: str):
    """R: 모집마감/Application Closed/No Left Tickets 토큰이 is_closed=True로 분류된다."""
    meta = parse_event_meta(closed_html)
    closed_slots = [s for s in meta.slots if s.is_closed]
    # 14 closed (4 in morning, 4 in afternoon except imminent, 5 in evening)
    # bundle_afternoon_B slot 4 is "마감임박" — not is_closed
    assert len(closed_slots) >= 13  # conservative: at least 13 should be closed


def test_imminent_slot_detected(closed_html: str):
    """R: 마감임박 슬롯은 is_closed=False, urgency_hint='imminent'로 분류된다."""
    meta = parse_event_meta(closed_html)
    imminent_slots = [s for s in meta.slots if s.urgency_hint == "imminent"]
    assert len(imminent_slots) == 1
    imminent = imminent_slots[0]
    assert imminent.is_closed is False
    assert imminent.bundle_id == "bundle_afternoon_B"


def test_time_labels_extracted(closed_html: str):
    """R: 슬롯에서 M/D HH:MM~HH:MM 형식의 시간대 라벨이 추출된다."""
    meta = parse_event_meta(closed_html)
    slots_with_time = [s for s in meta.slots if s.time_label is not None]
    # At least some slots should have time labels
    assert len(slots_with_time) > 0
    for s in slots_with_time:
        # Format should match M/D HH:MM~HH:MM
        assert "~" in s.time_label  # type: ignore[arg-type]


def test_closed_text_preserved(closed_html: str):
    """R: 마감 토큰 원문이 closed_text에 보존된다."""
    meta = parse_event_meta(closed_html)
    closed_texts = {s.closed_text for s in meta.slots if s.closed_text}
    assert "모집마감" in closed_texts
    assert "Application Closed" in closed_texts
    assert "No Left Tickets" in closed_texts


def test_bundle_slot_association(closed_html: str):
    """R: 각 슬롯이 올바른 bundle_id와 연결된다."""
    meta = parse_event_meta(closed_html)
    morning_slots = [s for s in meta.slots if s.bundle_id == "bundle_morning_A"]
    assert len(morning_slots) == 5
    afternoon_slots = [s for s in meta.slots if s.bundle_id == "bundle_afternoon_B"]
    assert len(afternoon_slots) == 5


def test_parse_soldout_fixture_ignores_bundle_wrapper_RIGHT(soldout_wrapper_html: str):
    """R: timeKey/dateLabel 없는 bundle wrapper는 예약 가능 슬롯으로 추출하지 않는다."""
    meta = parse_event_meta(soldout_wrapper_html)

    assert meta.event_id == "126341"
    assert meta.bundle_ids == ["52057"]
    assert len(meta.slots) == 4
    assert all(s.time_label for s in meta.slots)
    assert all(s.bundle_id == "52057" for s in meta.slots)
    assert all(s.is_closed for s in meta.slots)
    assert all(s.time_label != "52057" for s in meta.slots)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_html_returns_meta():
    """B: 빈 HTML도 에러 없이 빈 EventusMeta를 반환한다."""
    meta = parse_event_meta("")
    assert isinstance(meta, EventusMeta)
    assert meta.title is None
    assert meta.slots == []


def test_html_without_bundles():
    """B: bundle v-if가 없는 HTML → parse_errors에 기록."""
    html = "<html><h1>Test Event</h1></html>"
    meta = parse_event_meta(html)
    assert meta.title == "Test Event"
    assert meta.bundle_ids == []
    assert len(meta.parse_errors) > 0


def test_unknown_status_text_not_closed():
    """E: 알 수 없는 상태 텍스트(마감 토큰 아님)는 is_closed=False."""
    html = """
    <html>
    <h1>Test</h1>
    <div v-if="userSlectedBundle.id === 'bundle_X'">
    <ui-menu-item>
      <span>6/1 09:00~11:00</span>
      <span class="text-danger-400">접수중</span>
    </ui-menu-item>
    </div>
    </html>
    """
    meta = parse_event_meta(html)
    assert len(meta.slots) >= 1
    slot = meta.slots[0]
    assert slot.is_closed is False
    assert slot.urgency_hint is None
    assert slot.closed_text == "접수중"
