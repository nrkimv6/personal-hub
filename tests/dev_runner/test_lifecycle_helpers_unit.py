from __future__ import annotations

import pytest

from tests.dev_runner.dummy_plan_lifecycle_helpers import (
    DUMMY_PLAN_SENTINEL,
    FullLifecycleContext,
    MergePhaseBarrier,
    _run_git,
    assert_full_lifecycle_clean,
    assert_full_lifecycle_preserved,
    init_full_lifecycle_repo,
    init_multi_runner_lifecycle_repo,
)


def _ctx(tmp_path, *, runner_id: str = "t-helper-unit") -> FullLifecycleContext:
    repo_root, plan_path = init_full_lifecycle_repo(tmp_path, plan_name=f"{runner_id}.md")
    branch = f"runner/{runner_id}"
    worktree = repo_root / ".worktrees" / runner_id
    _run_git(repo_root, "worktree", "add", str(worktree), "-b", branch)
    archive_path = repo_root / "docs" / "archive" / plan_path.name
    marker_path = repo_root / "full-lifecycle-marker.txt"
    return FullLifecycleContext(
        repo_root=repo_root,
        runner_id=runner_id,
        runner_branch=branch,
        runner_worktree=worktree,
        original_plan_path=plan_path,
        archive_plan_path=archive_path,
        marker_path=marker_path,
    )


def test_assert_full_lifecycle_clean_reports_archive_missing(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.marker_path.write_text(DUMMY_PLAN_SENTINEL, encoding="utf-8")

    with pytest.raises(AssertionError, match="active plan residue"):
        assert_full_lifecycle_clean(ctx)


def test_assert_full_lifecycle_clean_reports_worktree_residue(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.marker_path.write_text(DUMMY_PLAN_SENTINEL, encoding="utf-8")
    ctx.archive_plan_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.archive_plan_path.write_text(
        "# done\n\n> 상태: 구현완료\n> 완료일: 2026-05-22\n> 진행률: 100%\n\n- [x] item\n",
        encoding="utf-8",
    )
    ctx.original_plan_path.unlink()

    with pytest.raises(AssertionError, match="worktree residue"):
        assert_full_lifecycle_clean(ctx)


def test_assert_full_lifecycle_clean_reports_branch_residue(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.marker_path.write_text(DUMMY_PLAN_SENTINEL, encoding="utf-8")
    ctx.archive_plan_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.archive_plan_path.write_text(
        "# done\n\n> 상태: 구현완료\n> 완료일: 2026-05-22\n> 진행률: 100%\n\n- [x] item\n",
        encoding="utf-8",
    )
    ctx.original_plan_path.unlink()
    _run_git(ctx.repo_root, "worktree", "remove", "--force", str(ctx.runner_worktree))

    with pytest.raises(AssertionError, match="branch residue"):
        assert_full_lifecycle_clean(ctx)


def test_assert_full_lifecycle_clean_rejects_pending_archive(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.marker_path.write_text(DUMMY_PLAN_SENTINEL, encoding="utf-8")
    ctx.archive_plan_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.archive_plan_path.write_text(
        "# pending\n\n> 상태: 머지대기\n> 완료일: 2026-05-22\n> 진행률: 100%\n\n- [x] item\n",
        encoding="utf-8",
    )
    ctx.original_plan_path.unlink()

    with pytest.raises(AssertionError, match="archive status not completed"):
        assert_full_lifecycle_clean(ctx)


def test_assert_full_lifecycle_preserved_accepts_terminal_preservation(tmp_path):
    ctx = _ctx(tmp_path)

    assert_full_lifecycle_preserved(ctx)


def test_init_multi_runner_lifecycle_repo_creates_distinct_runner_worktrees(tmp_path):
    multi = init_multi_runner_lifecycle_repo(tmp_path)

    assert len(multi.runner_contexts) == 2
    runner_ids = {ctx.runner_id for ctx in multi.runner_contexts}
    assert runner_ids == {"t-multi-runner-a", "t-multi-runner-b"}
    for ctx in multi.runner_contexts:
        assert ctx.runner_worktree.exists()
        assert ctx.original_plan_path.exists()
        assert ctx.runner_branch in _run_git(multi.repo_root, "branch", "--list", ctx.runner_branch).stdout


def test_merge_phase_barrier_records_arrival_and_release_order():
    barrier = MergePhaseBarrier(1)

    index = barrier.arrive("t-barrier-a", "merge")

    assert index == 0
    assert barrier.phases_for("t-barrier-a") == ["merge:arrive", "merge:release"]
