from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _skill_text(surface: str) -> str:
    return (ROOT / surface / "skills" / "merge-test" / "SKILL.md").read_text(encoding="utf-8")


def test_downstream_repo_has_no_common_tools_surface():
    assert not (ROOT / "common" / "tools").exists()


def test_agents_surface_documents_helper_unavailable_fallback():
    text = _skill_text(".agents")

    assert "helper_unavailable" in text
    assert "root branch main" in text
    assert "MERGE_HEAD 없음" in text
    assert "git status --short" in text
    assert "worktree-owner 일치" in text


def test_claude_surface_documents_helper_unavailable_fallback():
    text = _skill_text(".claude")

    assert "helper_unavailable" in text
    assert "proceed_with_manual_fallback" in text
    assert "explicit override" in text


def test_fallback_keeps_destructive_git_bans():
    text = _skill_text(".agents")

    assert "git reset --hard" in text
    assert "git clean -fd" in text
    assert "broad git add" in text
    assert "broad `git restore`" in text
