"""Unit tests for plan worktree metadata helpers."""
import pytest
from app.modules.dev_runner.services.plan_service import PlanService
from app.modules.dev_runner.services._plan_header_utils import validate_done_preconditions, update_plan_headers


# _extract_worktree_meta

def test__extract_worktree_meta_right():
    """R(Right): extracts and normalizes all three metadata fields."""
    content = (
        "# plan title\n"
        "> created_at: 2026-04-06\n"
        "> status: in_progress\n"
        "> branch: impl/feature-name\n"
        "> worktree: .worktrees/impl-feature-name\n"
        "> worktree-owner: docs/plan/2026-04-06_feature.md\n"
        "\n---\n"
    )
    result = PlanService._extract_worktree_meta(content)
    assert result["branch"] == "impl/feature-name"
    assert result["worktree_path"] == ".worktrees/impl-feature-name"
    assert result["worktree_owner"] == "docs/plan/2026-04-06_feature.md"


def test__extract_worktree_meta_empty():
    """B(Boundary): returns None for all metadata fields when headers are absent."""
    content = "# plan title\n> status: unknown\n\n---\n## overview\ncontent"
    result = PlanService._extract_worktree_meta(content)
    assert result["branch"] is None
    assert result["worktree_path"] is None
    assert result["worktree_owner"] is None


def test__extract_worktree_meta_partial():
    """B(Boundary): handles content with only branch metadata."""
    content = "# plan\n> branch: impl/feature\n> status: in_progress\n"
    result = PlanService._extract_worktree_meta(content)
    assert result["branch"] == "impl/feature"
    assert result["worktree_path"] is None
    assert result["worktree_owner"] is None


def test__extract_worktree_meta_normalize():
    """R(Right): normalizes equivalent path formats to the same result."""
    from pathlib import Path

    project_root = str(Path(__file__).resolve().parents[2]).replace("\\", "/").rstrip("/")

    # Absolute path with backslashes.
    content_backslash = (
        f"> branch: impl/f\n"
        f"> worktree: .worktrees/impl-f\n"
        f"> worktree-owner: {project_root.replace('/', chr(92))}\\docs\\plan\\test.md\n"
    )
    result_bs = PlanService._extract_worktree_meta(content_backslash)

    # Absolute path with forward slashes.
    content_slash = (
        f"> branch: impl/f\n"
        f"> worktree: .worktrees/impl-f\n"
        f"> worktree-owner: {project_root}/docs/plan/test.md\n"
    )
    result_sl = PlanService._extract_worktree_meta(content_slash)

    # Relative path.
    content_rel = (
        "> branch: impl/f\n"
        "> worktree: .worktrees/impl-f\n"
        "> worktree-owner: docs/plan/test.md\n"
    )
    result_rel = PlanService._extract_worktree_meta(content_rel)

    # Backslash and forward-slash absolute paths normalize identically.
    assert result_bs["worktree_owner"] == result_sl["worktree_owner"]
    # Absolute paths normalize to project-relative paths.
    assert result_bs["worktree_owner"] == "docs/plan/test.md", f"諛깆뒳?섏떆 ?덈?寃쎈줈?믪긽?寃쎈줈 蹂???ㅽ뙣: {result_bs['worktree_owner']}"
    assert result_sl["worktree_owner"] == "docs/plan/test.md", f"?щ옒???덈?寃쎈줈?믪긽?寃쎈줈 蹂???ㅽ뙣: {result_sl['worktree_owner']}"
    # Relative input remains unchanged.
    assert result_rel["worktree_owner"] == "docs/plan/test.md"


# _update_plan_headers

def test__update_plan_headers_removes_worktree_owner():
    """R(Right): removes all branch/worktree/worktree-owner metadata fields."""
    content = (
        "# plan\n"
        "> status: in_progress\n"
        "> progress: 5/5 (100%)\n"
        "> branch: impl/feature\n"
        "> worktree: .worktrees/impl-feature\n"
        "> worktree-owner: docs/plan/2026-04-06_feature.md\n"
        "\n---\n"
        "- [x] ??ぉ1\n"
        "*status: in_progress | progress: 5/5 (100%)*\n"
    )
    result = update_plan_headers(content, total=5)
    assert "branch" not in result or "> branch:" not in result
    assert "> worktree:" not in result
    assert "worktree-owner" not in result
    assert "in_progress" in result


# _validate_done_preconditions

def test__validate_done_preconditions_detects_worktree_owner():
    """E(Error): detects stale worktree metadata even when only owner remains."""
    content = (
        "# plan\n"
        "> status: completed\n"
        "> progress: 5/5 (100%)\n"
        "> worktree-owner: docs/plan/2026-04-06_feature.md\n"
        "\n---\n"
    )
    errors = validate_done_preconditions("plan.md", content)
    assert any("branch/worktree" in e for e in errors), f"?먮윭 誘멸컧吏: {errors}"


# Additional normalization coverage

def test__extract_worktree_meta_worktree_path_normalize():
    """R(Right): absolute worktree header values normalize to relative paths."""
    from pathlib import Path

    project_root = str(Path(__file__).resolve().parents[2]).replace("\\", "/").rstrip("/")

    content = (
        f"> branch: impl/f\n"
        f"> worktree: {project_root}/.worktrees/impl-f\n"
        "> worktree-owner: docs/plan/test.md\n"
    )
    result = PlanService._extract_worktree_meta(content)
    assert result["worktree_path"] == ".worktrees/impl-f", (
        f"?덈?寃쎈줈 ???곷?寃쎈줈 蹂???ㅽ뙣: {result['worktree_path']}"
    )


def test_project_root_is_monitor_page_dir():
    """R(Right): config.PROJECT_ROOT points at a monitor-page project root.

    In a linked worktree, PROJECT_ROOT should be the worktree root. In the main
    checkout, it should be the monitor-page root. In both cases it must exist
    and contain the app/ directory.
    """
    from app.core.config import PROJECT_ROOT
    assert PROJECT_ROOT.exists(), f"PROJECT_ROOT 議댁옱?섏? ?딆쓬: {PROJECT_ROOT}"
    assert (PROJECT_ROOT / "app").exists(), f"PROJECT_ROOT/app ?놁쓬: {PROJECT_ROOT}"
    # Allow either the main monitor-page directory or an implementation worktree.
    is_worktree = ".worktrees" in str(PROJECT_ROOT).replace("\\", "/")
    assert PROJECT_ROOT.name == "monitor-page" or is_worktree, (
        f"?덉긽移??딆? PROJECT_ROOT.name: '{PROJECT_ROOT.name}'"
    )


