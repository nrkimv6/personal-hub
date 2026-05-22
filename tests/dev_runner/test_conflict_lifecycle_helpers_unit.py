from __future__ import annotations

import subprocess

import fakeredis
import pytest

from tests.dev_runner._path_helpers import bootstrap_plan_runner_modules
from tests.dev_runner.dummy_plan_lifecycle_helpers import (
    DUMMY_PLAN_SENTINEL,
    RUNNER_KEY_PREFIX,
    FullLifecycleContext,
    assert_full_lifecycle_clean,
    assert_full_lifecycle_preserved,
    init_conflict_lifecycle_repo,
    init_full_lifecycle_repo,
)


def test_conflict_lifecycle_fixture_creates_real_git_conflict(tmp_path):
    ctx = init_conflict_lifecycle_repo(tmp_path)

    result = subprocess.run(
        ["git", "merge", ctx.runner_branch],
        cwd=str(ctx.repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert ctx.conflict_file_path is not None
    content = ctx.conflict_file_path.read_text(encoding="utf-8", errors="replace")
    assert "<<<<<<<" in content
    assert "MAIN_VERSION" in content
    assert "RUNNER_VERSION" in content

    subprocess.run(["git", "merge", "--abort"], cwd=str(ctx.repo_root), check=True, timeout=30)
    assert_full_lifecycle_preserved(ctx)


def test_conflict_lifecycle_fixture_preserved_helper_reports_deleted_worktree(tmp_path):
    ctx = init_conflict_lifecycle_repo(tmp_path)
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(ctx.runner_worktree)],
        cwd=str(ctx.repo_root),
        check=True,
        timeout=30,
    )

    with pytest.raises(AssertionError, match="worktree not preserved"):
        assert_full_lifecycle_preserved(ctx)


def _mark_plan_complete(plan_path):
    text = plan_path.read_text(encoding="utf-8", errors="replace")
    text = text.replace("[ ]", "[x]")
    text = text.replace("> 상태: 구현중", "> 상태: 머지대기")
    text = text.replace("> 진행률: 0/1 (0%)", "> 진행률: 1/1 (100%)")
    text = text.replace("*상태: 구현중 | 진행률: 0/1 (0%)*", "*상태: 머지대기 | 진행률: 1/1 (100%)*")
    plan_path.write_text(text, encoding="utf-8")


def test_handle_conflict_success_archives_with_test_done_seam(tmp_path, monkeypatch):
    bootstrap_plan_runner_modules()
    import _dr_merge

    repo_root, plan_path = init_full_lifecycle_repo(tmp_path, plan_name="2026-05-22_test-conflict-success.md")
    _mark_plan_complete(plan_path)
    marker_path = repo_root / "full-lifecycle-marker.txt"
    marker_path.write_text(f"{DUMMY_PLAN_SENTINEL}\n", encoding="utf-8")

    redis_client = fakeredis.FakeRedis(decode_responses=True)
    runner_id = "t-conflict-success"
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:test_source", "conflict")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:test_repo_root", str(repo_root))
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", str(repo_root / ".worktrees" / runner_id))
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", f"runner/{runner_id}")

    monkeypatch.setenv("DEV_RUNNER_ALLOW_TEST_REPO_ROOT", "1")
    monkeypatch.setenv("DEV_RUNNER_TEST_IN_PROCESS_DONE", "1")
    monkeypatch.setattr(
        _dr_merge,
        "_launch_conflict_resolver_process",
        lambda **kwargs: {"success": True, "message": "resolved", "merge_status": "merged", "conflict": False},
    )

    result = _dr_merge._handle_conflict(
        runner_id,
        redis_client,
        str(plan_path),
        pub_fn=lambda msg: None,
        branch_str=f"runner/{runner_id}",
    )

    assert result["success"] is True
    ctx = FullLifecycleContext(
        repo_root=repo_root,
        runner_id=runner_id,
        runner_branch=f"runner/{runner_id}",
        runner_worktree=repo_root / ".worktrees" / runner_id,
        original_plan_path=plan_path,
        archive_plan_path=repo_root / "docs" / "archive" / plan_path.name,
        marker_path=marker_path,
    )
    assert_full_lifecycle_clean(ctx)


def test_handle_conflict_failure_preserves_plan_worktree_and_branch(tmp_path, monkeypatch):
    bootstrap_plan_runner_modules()
    import _dr_merge

    ctx = init_conflict_lifecycle_repo(tmp_path, runner_id="t-conflict-failure")
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}:test_source", "conflict")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}:test_repo_root", str(ctx.repo_root))
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}:worktree_path", str(ctx.runner_worktree))
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}:branch", ctx.runner_branch)

    monkeypatch.setenv("DEV_RUNNER_ALLOW_TEST_REPO_ROOT", "1")
    monkeypatch.setattr(
        _dr_merge,
        "_launch_conflict_resolver_process",
        lambda **kwargs: {
            "success": False,
            "message": "unsafe conflict requires manual resolution",
            "merge_status": "conflict",
            "conflict": True,
        },
    )

    result = _dr_merge._handle_conflict(
        ctx.runner_id,
        redis_client,
        str(ctx.original_plan_path),
        pub_fn=lambda msg: None,
        branch_str=ctx.runner_branch,
    )

    assert result["success"] is False
    assert result["merge_status"] == "conflict"
    assert redis_client.get(f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}:merge_status") == "conflict"
    assert_full_lifecycle_preserved(ctx)
