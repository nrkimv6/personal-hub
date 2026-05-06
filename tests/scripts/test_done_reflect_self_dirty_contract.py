"""Static contract tests for wtools self-dirty commit guarantees."""
import os
import subprocess
from pathlib import Path

_here = Path(__file__).resolve()
_PLAN_SLUG = "2026-05-04_fix-plans-worktree-commit-guarantee-guard"


def _project_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=_here.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return _here.parents[2]


def _workspace_root() -> Path:
    root = _project_root()
    for parent in (root, *root.parents):
        if parent.name == "project":
            return parent
    return _here.parents[6]


def _resolve_wtools_root() -> Path:
    env_root = os.environ.get("WTOOLS_ROOT")
    if env_root and Path(env_root).exists():
        return Path(env_root)

    workspace = _workspace_root()
    worktree_candidate = workspace / "service" / "wtools" / ".worktrees" / f"impl-{_PLAN_SLUG}"
    if worktree_candidate.exists():
        return worktree_candidate

    return workspace / "service" / "wtools"


WTOOLS_ROOT = _resolve_wtools_root()

_REQUIRED_TERMS = ("baseline dirty paths", "touched paths", "self residual dirty")
_TOUCHED_WHITELIST_TERMS = ("touched whitelist dirty", "exact path set", "hard-fail")


def _skill_path(surface: str, skill: str, filename: str = "SKILL.md") -> Path:
    return WTOOLS_ROOT / surface / "skills" / skill / filename


def _read_skill(surface: str, skill: str, filename: str = "SKILL.md") -> str:
    path = _skill_path(surface, skill, filename)
    if not path.exists():
        raise FileNotFoundError(f"skill contract file not found: {path}")
    return path.read_text(encoding="utf-8")


def test_agents_done_has_self_dirty_terms():
    text = _read_skill(".agents", "done")
    for term in _REQUIRED_TERMS:
        assert term in text, f"agents done SKILL.md missing '{term}'"


def test_agents_reflect_has_self_dirty_terms():
    text = _read_skill(".agents", "reflect")
    for term in _REQUIRED_TERMS:
        assert term in text, f"agents reflect SKILL.md missing '{term}'"


def test_claude_done_mirrors_agents():
    text = _read_skill(".claude", "done")
    for term in _REQUIRED_TERMS:
        assert term in text, f"claude done SKILL.md missing '{term}'"


def test_claude_reflect_mirrors_agents():
    text = _read_skill(".claude", "reflect")
    for term in _REQUIRED_TERMS:
        assert term in text, f"claude reflect SKILL.md missing '{term}'"


def test_touched_preexisting_in_done():
    text = _read_skill(".agents", "done")
    assert "touched preexisting dirty" in text, "agents done missing touched preexisting dirty"
    assert "whitelist 안" in text or "커밋 대상에 포함" in text, (
        "agents done missing preexisting dirty whitelist handling"
    )


def test_agents_done_has_touched_whitelist_commit_terms():
    text = _read_skill(".agents", "done") + _read_skill(".agents", "done", "_recipes.md")
    for term in _TOUCHED_WHITELIST_TERMS:
        assert term in text, f"agents done contract missing '{term}'"


def test_claude_done_has_touched_whitelist_commit_terms():
    text = _read_skill(".claude", "done") + _read_skill(".claude", "done", "_recipes.md")
    for term in _TOUCHED_WHITELIST_TERMS:
        assert term in text, f"claude done contract missing '{term}'"


def test_agents_review_plan_has_commit_guarantee_terms():
    text = _read_skill(".agents", "review-plan")
    for term in ("expand-todo", "touched paths", "touched whitelist dirty", "commit", "hard-fail"):
        assert term in text, f"agents review-plan contract missing '{term}'"


def test_claude_review_plan_has_commit_guarantee_terms():
    text = _read_skill(".claude", "review-plan")
    for term in ("expand-todo", "touched paths", "touched whitelist dirty", "commit", "hard-fail"):
        assert term in text, f"claude review-plan contract missing '{term}'"


def test_agents_expand_todo_has_commit_output_terms():
    text = _read_skill(".agents", "expand-todo")
    for term in ("commit hash", "no-op", "touched whitelist dirty"):
        assert term in text, f"agents expand-todo contract missing '{term}'"


def test_claude_expand_todo_has_commit_output_terms():
    text = _read_skill(".claude", "expand-todo")
    for term in ("commit hash", "no-op", "touched whitelist dirty"):
        assert term in text, f"claude expand-todo contract missing '{term}'"


def test_agents_implement_has_pre_edit_handoff_terms():
    text = _read_skill(".agents", "implement")
    for term in ("pre-edit status/header mutation", "docs commit", "handoff evidence"):
        assert term in text, f"agents implement contract missing '{term}'"


def test_claude_implement_has_pre_edit_handoff_terms():
    text = _read_skill(".claude", "implement")
    for term in ("pre-edit status/header mutation", "docs commit", "handoff evidence"):
        assert term in text, f"claude implement contract missing '{term}'"


def test_skill_missing_raises_clear_error(tmp_path):
    missing = tmp_path / ".agents" / "skills" / "missing" / "SKILL.md"
    try:
        if not missing.exists():
            raise FileNotFoundError(f"skill contract file not found: {missing}")
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("missing skill file did not raise FileNotFoundError")


def test_plans_worktree_both_checked_in_done():
    text = _read_skill(".agents", "done")
    assert ".worktrees/plans" in text, "agents done missing .worktrees/plans"
    assert "git status" in text, "agents done missing git status"
