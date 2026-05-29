import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "tools" / "chrome-api-capture-extension"


def test_manifest_is_mv3_scoped_and_debugger_free():
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == 3
    assert "debugger" not in manifest["permissions"]
    assert manifest["host_permissions"] == ["https://new.land.naver.com/*"]
    assert manifest["content_scripts"][0]["matches"] == ["https://new.land.naver.com/*"]
    assert manifest["background"]["service_worker"] == "background.js"
    assert manifest["action"]["default_popup"] == "popup.html"
