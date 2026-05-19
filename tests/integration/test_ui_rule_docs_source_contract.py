from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_sidebar_menu_rule_is_documented_in_owned_docs() -> None:
    claude = _read("CLAUDE.md")
    layout_guide = _read("docs/dev-guide/frontend-layout-guide.md")

    for source in (claude, layout_guide):
        assert "사이드바" in source
        assert "frontend/src/lib/navigation.ts" in source
        assert "frontend/src/routes/*/+layout.svelte" in source
        assert "사용자가 명시" in source
        assert "기존 메뉴 하위 라우트" in source

    assert "MONITOR_TYPE_META.createHref" in layout_guide
    assert ".claude/.agents/.agent/.gemini" in layout_guide


def test_ui_symptom_observation_rule_is_documented_in_owned_docs() -> None:
    claude = _read("CLAUDE.md")
    troubleshooting = _read("docs/dev-guide/troubleshooting.md")

    for source in (claude, troubleshooting):
        assert "UI 증상" in source
        assert "Playwright" in source
        assert "Browser" in source
        assert "snapshot/screenshot/read-back" in source
        assert "코드" in source
        assert "정상" in source

    assert "화면 관찰을 대체하지 않는다" in troubleshooting
