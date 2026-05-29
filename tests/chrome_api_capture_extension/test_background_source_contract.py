from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "tools" / "chrome-api-capture-extension" / "background.js").read_text(encoding="utf-8")


def test_webrequest_listeners_are_registered():
    for listener in [
        "onBeforeRequest",
        "onBeforeSendHeaders",
        "onHeadersReceived",
        "onBeforeRedirect",
        "onCompleted",
        "onErrorOccurred",
    ]:
        assert f"chrome.webRequest.{listener}.addListener" in SOURCE


def test_header_masking_and_cache_warning_contract():
    assert "function maskHeaders(headers = [], includeSensitive = false)" in SOURCE
    assert "[masked-sensitive-header]" in SOURCE
    assert "authorization" in SOURCE
    assert "cookie" in SOURCE
    assert "in-memory cache hits" in SOURCE


def test_replay_allows_only_get_head_and_blocks_mutating_methods():
    assert 'new Set(["GET", "HEAD"])' in SOURCE
    assert "REPLAY_ALLOWED_METHODS.has(method)" in SOURCE
    assert "mutating method" in SOURCE
    assert 'credentials: "omit"' in SOURCE
