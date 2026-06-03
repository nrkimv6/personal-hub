"""Aladin buyback HTML parser tests."""

from pathlib import Path

from app.modules.books.aladin_buyback import parse_aladin_buyback_html, should_use_playwright_fallback

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_search_success_R_condition_prices():
    result = parse_aladin_buyback_html(read_fixture("aladin_buyback_search_success.html"), "9788937460449")

    assert result.availability == "yes"
    assert {quote.grade: quote.price for quote in result.quotes} == {"최상": 3000, "상": 2700, "중": 2400}


def test_parse_multi_result_R_matches_isbn():
    result = parse_aladin_buyback_html(read_fixture("aladin_buyback_search_multi.html"), "9788937460449")

    assert result.availability == "yes"
    assert {quote.grade: quote.price for quote in result.quotes} == {"최상": 3000, "상": 2700, "중": 2400}


def test_parse_not_buying_B_availability_no():
    result = parse_aladin_buyback_html(read_fixture("aladin_buyback_search_not_buying.html"), "9788937473135")

    assert result.availability == "no"
    assert result.raw_status == "not_buying"
    assert result.quotes == []


def test_parse_drift_E_playwright_fallback_condition():
    result = parse_aladin_buyback_html("<html><body>ISBN 9788937460449</body></html>", "9788937460449")

    assert result.availability == "error"
    assert should_use_playwright_fallback(result) is True
