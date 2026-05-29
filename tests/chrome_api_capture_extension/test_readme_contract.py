from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "tools" / "chrome-api-capture-extension" / "README.md").read_text(encoding="utf-8")


def test_readme_documents_scope_sensitive_data_and_install_steps():
    assert "https://new.land.naver.com/*" in README
    assert "Sensitive Data Warning" in README
    assert "Do not commit exported JSON" in README
    assert "chrome://extensions" in README
    assert "Load unpacked" in README


def test_readme_documents_replay_and_manual_smoke_limits():
    assert "POST, PUT, PATCH, DELETE" in README
    assert "blocked reason" in README
    assert "bulk replay" in README
    assert "Manual Smoke Handoff" in README
    assert "fixtures/local-api.html" in README
