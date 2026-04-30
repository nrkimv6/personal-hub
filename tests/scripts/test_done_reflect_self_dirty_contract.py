"""정적 계약 TC: done/reflect .agents + .claude 스킬 파일에 self dirty 계약 문구가 포함되는지 검증."""
from pathlib import Path

_here = Path(__file__).resolve()
# main tree: parents[4] = D:/work/project
# worktree:  parents[6] = D:/work/project
_candidate = _here.parents[4] / "service" / "wtools"
if not _candidate.exists():
    _candidate = _here.parents[6] / "service" / "wtools"
WTOOLS_ROOT = _candidate

AGENTS_DONE = WTOOLS_ROOT / ".agents/skills/done/SKILL.md"
AGENTS_REFLECT = WTOOLS_ROOT / ".agents/skills/reflect/SKILL.md"
CLAUDE_DONE = WTOOLS_ROOT / ".claude/skills/done/SKILL.md"
CLAUDE_REFLECT = WTOOLS_ROOT / ".claude/skills/reflect/SKILL.md"

_REQUIRED_TERMS = ("baseline dirty paths", "touched paths", "self residual dirty")


def test_agents_done_has_self_dirty_terms():
    text = AGENTS_DONE.read_text(encoding="utf-8")
    for term in _REQUIRED_TERMS:
        assert term in text, f"agents done SKILL.md에 '{term}' 없음"


def test_agents_reflect_has_self_dirty_terms():
    text = AGENTS_REFLECT.read_text(encoding="utf-8")
    for term in _REQUIRED_TERMS:
        assert term in text, f"agents reflect SKILL.md에 '{term}' 없음"


def test_claude_done_mirrors_agents():
    text = CLAUDE_DONE.read_text(encoding="utf-8")
    for term in _REQUIRED_TERMS:
        assert term in text, f"claude done SKILL.md에 '{term}' 없음"


def test_claude_reflect_mirrors_agents():
    text = CLAUDE_REFLECT.read_text(encoding="utf-8")
    for term in _REQUIRED_TERMS:
        assert term in text, f"claude reflect SKILL.md에 '{term}' 없음"


def test_touched_preexisting_in_done():
    text = AGENTS_DONE.read_text(encoding="utf-8")
    assert "touched preexisting dirty" in text, "agents done에 'touched preexisting dirty' 없음"
    assert "whitelist 안" in text or "커밋 대상에 포함" in text, (
        "agents done에 preexisting dirty whitelist 처리 문구 없음"
    )


def test_plans_worktree_both_checked_in_done():
    text = AGENTS_DONE.read_text(encoding="utf-8")
    assert ".worktrees/plans" in text, "agents done에 '.worktrees/plans' 없음"
    assert "git status" in text, "agents done에 'git status' 없음"
