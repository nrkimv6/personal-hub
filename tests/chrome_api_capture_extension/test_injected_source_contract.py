from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "tools" / "chrome-api-capture-extension" / "injected.js").read_text(encoding="utf-8")


def test_fetch_hook_uses_response_clone_and_body_limit():
    assert "function installFetchHook()" in SOURCE
    assert "window.fetch = async function captureFetch" in SOURCE
    assert "response.clone().text()" in SOURCE
    assert "const BODY_TEXT_LIMIT = 65536" in SOURCE
    assert "truncated: true" in SOURCE


def test_xhr_hook_and_duplicate_install_sentinel_exist():
    assert "function installXhrHook()" in SOURCE
    assert "XMLHttpRequest" in SOURCE
    assert "__CHROME_API_CAPTURE_HOOK_INSTALLED__" in SOURCE
    assert "if (window[SENTINEL])" in SOURCE
