from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "tools" / "chrome-api-capture-extension"
HTML = (EXTENSION / "popup.html").read_text(encoding="utf-8")
JS = (EXTENSION / "popup.js").read_text(encoding="utf-8")


def test_popup_contains_capture_export_clear_and_replay_guard_ui():
    assert "captureToggle" in HTML
    assert "clearTab" in HTML
    assert "clearAll" in HTML
    assert "exportJson" in HTML
    assert "exportNdjson" in HTML
    assert "replayGuard" in HTML
    assert "GET/HEAD only" in HTML


def test_popup_replay_button_blocks_mutating_methods():
    assert "function methodAllowsReplay(method)" in JS
    assert '["GET", "HEAD"]' in JS
    assert "Replay blocked" in JS
    assert "downloadExport" in JS
    assert "includeSensitive: false" in JS
