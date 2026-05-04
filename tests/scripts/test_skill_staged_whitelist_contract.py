"""Static contract tests for local skill mirror staged whitelist rules."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_done_mirrors_require_exact_staged_set() -> None:
    for path in (
        ".agents/skills/done/SKILL.md",
        ".claude/skills/done/SKILL.md",
    ):
        text = _read(path)
        assert "exact path set" in text
        assert "git diff --cached --name-status" in text
        assert "staged mismatch" in text
        assert "git add -A" in text


def test_review_plan_mirrors_restrict_docs_staging() -> None:
    for path in (
        ".agents/skills/review-plan/SKILL.md",
        ".claude/skills/review-plan/SKILL.md",
    ):
        text = _read(path)
        assert "git add -A" in text
        assert "화이트리스트" in text
        assert "commit.ps1 -Files" in text


def test_reflect_mirrors_have_exact_match_fallback_guard() -> None:
    for path in (
        ".agents/skills/reflect/SKILL.md",
        ".claude/skills/reflect/SKILL.md",
    ):
        text = _read(path)
        assert "화이트리스트 exact-match 검증" in text
        assert "커밋하지 않고" in text
        assert "화이트리스트 커밋" in text
