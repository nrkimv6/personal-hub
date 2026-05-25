"""Tests for eventus_reservation.services.analyzer."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.modules.eventus_reservation.services.analyzer import (
    EventusAnalyzeResult,
    EventusAnalyzer,
)
from app.modules.eventus_reservation.services.event_resolver import (
    EventIdResolverError,
    EventusEventResolver,
    ResolvedEventusUrl,
)
from app.modules.eventus_reservation.services.http_client import EventusHttpClient
from app.modules.eventus_reservation.utils.url_parser import normalize_eventus_input

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CLOSED_HTML = (FIXTURE_DIR / "eventus_126341_closed.html").read_text(encoding="utf-8")
_SOURCE_URL = "https://event-us.kr/age20scoffee/event/126341"


def _make_analyzer(html: str, source_url: str = _SOURCE_URL) -> EventusAnalyzer:
    """Return analyzer with fake HTTP client returning fixed html."""
    client = MagicMock(spec=EventusHttpClient)
    client.fetch_event_page = AsyncMock(return_value=html)
    resolver = EventusEventResolver()
    return EventusAnalyzer(http_client=client, resolver=resolver)


# ---------------------------------------------------------------------------
# URL input path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_url_returns_title():
    """R: URL 입력 → title 추출 성공."""
    analyzer = _make_analyzer(CLOSED_HTML)
    inp = normalize_eventus_input(_SOURCE_URL)
    result = await analyzer.analyze(inp)
    assert isinstance(result, EventusAnalyzeResult)
    assert result.error_code is None
    assert result.title is not None
    assert "커피챗" in result.title or "네트워킹" in result.title


@pytest.mark.asyncio
async def test_analyze_url_returns_bundles():
    """R: URL 입력 → bundle IDs 반환."""
    analyzer = _make_analyzer(CLOSED_HTML)
    inp = normalize_eventus_input(_SOURCE_URL)
    result = await analyzer.analyze(inp)
    assert len(result.bundles) == 3


@pytest.mark.asyncio
async def test_analyze_url_returns_slots():
    """R: URL 입력 → slots 반환."""
    analyzer = _make_analyzer(CLOSED_HTML)
    inp = normalize_eventus_input(_SOURCE_URL)
    result = await analyzer.analyze(inp)
    assert len(result.slots) > 0


@pytest.mark.asyncio
async def test_analyze_url_closed_token_count():
    """R: URL 입력 → closed_token_counts 반환."""
    analyzer = _make_analyzer(CLOSED_HTML)
    inp = normalize_eventus_input(_SOURCE_URL)
    result = await analyzer.analyze(inp)
    assert result.closed_token_counts >= 13


# ---------------------------------------------------------------------------
# event_id-only input → resolver error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_event_id_only_returns_resolver_error():
    """R: event_id 단독 입력은 event_id_resolver_error를 반환한다."""
    analyzer = _make_analyzer(CLOSED_HTML)
    inp = normalize_eventus_input("126341")  # digits only
    result = await analyzer.analyze(inp)
    assert result.error_code == "event_id_resolver_error"
    assert result.error_message is not None
    assert "126341" in result.error_message


# ---------------------------------------------------------------------------
# Bot-block detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_short_html_returns_bot_block():
    """R: HTML이 임계값보다 짧으면 bot_block_suspected를 반환한다."""
    short_html = "<html><body>Blocked</body></html>"  # < 2000 chars
    analyzer = _make_analyzer(short_html)
    inp = normalize_eventus_input(_SOURCE_URL)
    result = await analyzer.analyze(inp)
    assert result.error_code == "bot_block_suspected"


@pytest.mark.asyncio
async def test_analyze_html_without_landmark_returns_bot_block():
    """R: HTML에 'event-us' 랜드마크가 없으면 bot_block_suspected를 반환한다."""
    html_no_landmark = "x" * 3000  # long enough but no landmark
    analyzer = _make_analyzer(html_no_landmark)
    inp = normalize_eventus_input(_SOURCE_URL)
    result = await analyzer.analyze(inp)
    assert result.error_code == "bot_block_suspected"


# ---------------------------------------------------------------------------
# Fetch error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_fetch_error_returns_fetch_error():
    """E: HTTP client가 예외를 던지면 fetch_error를 반환한다."""
    client = MagicMock(spec=EventusHttpClient)
    client.fetch_event_page = AsyncMock(side_effect=RuntimeError("Eventus HTTP 403: url"))
    analyzer = EventusAnalyzer(http_client=client)
    inp = normalize_eventus_input(_SOURCE_URL)
    result = await analyzer.analyze(inp)
    assert result.error_code == "fetch_error"
    assert "403" in (result.error_message or "")
