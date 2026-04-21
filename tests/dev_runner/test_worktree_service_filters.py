from pathlib import Path

from app.modules.dev_runner.services.worktree_service import (
    compute_cleanable,
    find_plan_file,
    is_test_branch,
)


def _write_plan(path: Path, branch: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# test",
                f"> branch: {branch}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_is_test_branch_matches_runner_prefix():
    assert is_test_branch("runner/t-t5envhdr-1e2c") is True


def test_is_test_branch_matches_plan_prefixes():
    assert is_test_branch("plan/test_minimal_plan") is True
    assert is_test_branch("plan/t-test-foo") is True


def test_is_test_branch_rejects_empty_string():
    assert is_test_branch("") is False


def test_is_test_branch_ignores_impl_branch():
    assert is_test_branch("impl/fix-foo") is False


def test_is_test_branch_ignores_non_test_plan_branch():
    assert is_test_branch("plan/2026-04-20_foo") is False


def test_compute_cleanable_accepts_no_plan_when_ahead_zero():
    assert compute_cleanable(locked=False, ahead=0, plan_file=None, archived=False) is True


def test_compute_cleanable_accepts_archived_plan():
    assert compute_cleanable(
        locked=False,
        ahead=0,
        plan_file="docs/archive/test.md",
        archived=True,
    ) is True


def test_compute_cleanable_rejects_locked_ahead_and_active_plan():
    assert compute_cleanable(locked=True, ahead=0, plan_file=None, archived=False) is False
    assert compute_cleanable(locked=False, ahead=1, plan_file=None, archived=False) is False
    assert compute_cleanable(
        locked=False,
        ahead=0,
        plan_file="docs/plan/test.md",
        archived=False,
    ) is False


def test_compute_cleanable_accepts_behind_only_when_ahead_zero():
    assert compute_cleanable(
        locked=False,
        ahead=0,
        plan_file="docs/archive/behind-only.md",
        archived=True,
    ) is True


def test_find_plan_file_finds_active_then_archive(tmp_path: Path):
    repo_root = tmp_path
    active = repo_root / ".worktrees" / "plans" / "docs" / "plan" / "active.md"
    archived = repo_root / ".worktrees" / "plans" / "docs" / "archive" / "archived.md"
    _write_plan(active, "impl/test-branch")
    _write_plan(archived, "impl/archived-branch")

    active_result = find_plan_file("impl/test-branch", repo_root)
    archived_result = find_plan_file("impl/archived-branch", repo_root)

    assert active_result[0].replace("\\", "/") == ".worktrees/plans/docs/plan/active.md"
    assert active_result[2] is False
    assert archived_result[0].replace("\\", "/") == ".worktrees/plans/docs/archive/archived.md"
    assert archived_result[2] is True


def test_find_plan_file_prefers_active_over_archive(tmp_path: Path):
    repo_root = tmp_path
    active = repo_root / ".worktrees" / "plans" / "docs" / "plan" / "same.md"
    archived = repo_root / ".worktrees" / "plans" / "docs" / "archive" / "same.md"
    _write_plan(active, "impl/shared-branch")
    _write_plan(archived, "impl/shared-branch")

    result = find_plan_file("impl/shared-branch", repo_root)

    assert result[0].replace("\\", "/") == ".worktrees/plans/docs/plan/same.md"
    assert result[2] is False


def test_find_plan_file_returns_none_when_missing(tmp_path: Path):
    assert find_plan_file("impl/missing", tmp_path) == (None, None, False)
