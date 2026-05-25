"""Tests for eventus_reservation.utils.url_parser."""

import pytest
from app.modules.eventus_reservation.utils.url_parser import (
    EventusEventUrl,
    EventusInput,
    normalize_eventus_input,
    parse_eventus_event_url,
)


# ---------------------------------------------------------------------------
# parse_eventus_event_url — RIGHT
# ---------------------------------------------------------------------------

def test_parse_standard_url():
    """R: 정상 Eventus URL → organizer_slug, event_id 추출."""
    result = parse_eventus_event_url("https://event-us.kr/age20scoffee/event/126341")
    assert isinstance(result, EventusEventUrl)
    assert result.organizer_slug == "age20scoffee"
    assert result.event_id == "126341"
    assert result.source_url == "https://event-us.kr/age20scoffee/event/126341"


def test_parse_url_trailing_slash():
    """R: trailing slash 있는 URL도 파싱된다."""
    result = parse_eventus_event_url("https://event-us.kr/myorg/event/99999/")
    assert result.organizer_slug == "myorg"
    assert result.event_id == "99999"


def test_parse_url_http_scheme():
    """R: http scheme도 허용."""
    result = parse_eventus_event_url("http://event-us.kr/testorg/event/12345")
    assert result.event_id == "12345"


# ---------------------------------------------------------------------------
# parse_eventus_event_url — Boundary / Error
# ---------------------------------------------------------------------------

def test_parse_empty_string_raises():
    """B: 빈 문자열 → ValueError."""
    with pytest.raises(ValueError, match="Invalid Eventus event URL"):
        parse_eventus_event_url("")


def test_parse_whitespace_raises():
    """B: 공백 문자열 → ValueError."""
    with pytest.raises(ValueError, match="Invalid Eventus event URL"):
        parse_eventus_event_url("   ")


def test_parse_wrong_host_raises():
    """E: 다른 호스트 URL → ValueError."""
    with pytest.raises(ValueError, match="Invalid Eventus event URL"):
        parse_eventus_event_url("https://example.com/org/event/12345")


def test_parse_missing_event_id_raises():
    """E: event_id 없는 URL → ValueError."""
    with pytest.raises(ValueError, match="Invalid Eventus event URL"):
        parse_eventus_event_url("https://event-us.kr/age20scoffee/event/")


def test_parse_missing_organizer_raises():
    """E: organizer 없는 URL → ValueError."""
    with pytest.raises(ValueError, match="Invalid Eventus event URL"):
        parse_eventus_event_url("https://event-us.kr/event/126341")


def test_parse_non_digit_event_id_raises():
    """E: event_id가 숫자가 아닌 URL → ValueError."""
    with pytest.raises(ValueError, match="Invalid Eventus event URL"):
        parse_eventus_event_url("https://event-us.kr/org/event/abc")


# ---------------------------------------------------------------------------
# normalize_eventus_input — RIGHT
# ---------------------------------------------------------------------------

def test_normalize_digit_only_input():
    """R: 숫자 event_id 단독 입력 → EventusInput(event_id=..., source_url=None)."""
    result = normalize_eventus_input("126341")
    assert isinstance(result, EventusInput)
    assert result.event_id == "126341"
    assert result.source_url is None
    assert result.organizer_slug is None


def test_normalize_full_url_input():
    """R: 전체 URL 입력 → EventusInput에 모든 필드 채워짐."""
    result = normalize_eventus_input("https://event-us.kr/age20scoffee/event/126341")
    assert result.event_id == "126341"
    assert result.source_url == "https://event-us.kr/age20scoffee/event/126341"
    assert result.organizer_slug == "age20scoffee"


def test_normalize_strips_whitespace():
    """B: 앞뒤 공백 제거 후 처리."""
    result = normalize_eventus_input("  126341  ")
    assert result.event_id == "126341"
    assert result.source_url is None


# ---------------------------------------------------------------------------
# normalize_eventus_input — Error
# ---------------------------------------------------------------------------

def test_normalize_empty_raises():
    """E: 빈 입력 → ValueError."""
    with pytest.raises(ValueError):
        normalize_eventus_input("")


def test_normalize_invalid_url_raises():
    """E: 잘못된 URL 형식 → ValueError."""
    with pytest.raises(ValueError):
        normalize_eventus_input("https://other-site.com/event/123")
