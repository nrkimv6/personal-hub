"""Nightly repo sync service contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.modules.dev_runner.services.nightly_repo_sync_service import (
    BLOCK_MIRROR_CONFLICT,
    BLOCK_PLANS_POLICY_CHANGE,
    BLOCK_ROOT_DIRTY,
    BLOCK_VERIFICATION_FAILED,
    NightlyRepoSyncService,
    _is_destructive_git_command,
    is_mirror_surface_path,
    is_plans_commit_whitelisted,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    (path / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
    (path / "README.md").write_text("init\n", encoding="utf-8")
    _git(path, "add", ".gitignore", "README.md")
    _git(path, "commit", "-m", "init")
    _git(path, "branch", "-M", "main")
    return path


def _init_repo_with_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", str(origin))
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    return repo


def _clone_origin(repo: Path, tmp_path: Path) -> Path:
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(repo / ".." / "origin.git"), str(other))
    _git(other, "checkout", "main")
    _git(other, "config", "user.email", "other@example.com")
    _git(other, "config", "user.name", "Other User")
    return other


def _add_plans_worktree(repo: Path) -> Path:
    plans = repo / ".worktrees" / "plans"
    _git(repo, "worktree", "add", "-b", "plans", str(plans))
    (plans / "TODO.md").write_text("# TODO\n", encoding="utf-8")
    _git(plans, "add", "TODO.md")
    _git(plans, "commit", "-m", "docs: init plans")
    _git(plans, "push", "-u", "origin", "plans")
    (plans / "docs" / "history").mkdir(parents=True)
    (plans / "docs" / "history" / "run.md").write_text("# run\n", encoding="utf-8")
    _git(plans, "add", "docs/history/run.md")
    _git(plans, "commit", "-m", "docs: local plans change")
    return plans


def test_collect_snapshot_right_root_and_plans_ahead_behind(tmp_path: Path) -> None:
    repo = _init_repo_with_origin(tmp_path)
    plans = _add_plans_worktree(repo)

    service = NightlyRepoSyncService(repo)
    snapshot = service.collect_snapshot(fetch=False)

    assert snapshot.root.name == "main"
    assert snapshot.root.ahead == 0
    assert snapshot.root.behind == 0
    assert snapshot.plans is not None
    assert snapshot.plans.name == "plans"
    assert snapshot.plans.ahead == 1
    assert plans.exists()


def test_plans_commit_co_only_whitelisted_docs_are_staged(tmp_path: Path) -> None:
    repo = _init_repo_with_origin(tmp_path)
    plans = _add_plans_worktree(repo)
    (plans / "docs" / "plan").mkdir(parents=True)
    (plans / "docs" / "plan" / "a.md").write_text("# a\n", encoding="utf-8")

    service = NightlyRepoSyncService(repo, commit_script=tmp_path / "missing.ps1")
    decision = service.commit_plans_changes()

    assert decision.allowed is False
    assert decision.block_reason == BLOCK_PLANS_POLICY_CHANGE
    assert decision.blocked_files == []
    assert decision.staged_files == ["docs/plan/a.md"]


def test_plans_commit_error_policy_change_blocks_commit(tmp_path: Path) -> None:
    repo = _init_repo_with_origin(tmp_path)
    plans = _add_plans_worktree(repo)
    (plans / "app.py").write_text("print('policy')\n", encoding="utf-8")

    decision = NightlyRepoSyncService(repo).commit_plans_changes()

    assert decision.allowed is False
    assert decision.block_reason == BLOCK_PLANS_POLICY_CHANGE
    assert decision.blocked_files == ["app.py"]


def test_main_sync_boundary_root_dirty_blocks_mutation(tmp_path: Path) -> None:
    repo = _init_repo_with_origin(tmp_path)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    result = NightlyRepoSyncService(repo).sync_main_ff_or_push()

    assert result.status == "blocked"
    assert result.block_reason == BLOCK_ROOT_DIRTY


def test_mirror_conflict_error_blocks_llm_resolve() -> None:
    assert is_mirror_surface_path(".agents/skills/implement/SKILL.md") is True
    assert is_mirror_surface_path(".claude/agents/auto-impl.md") is True
    assert is_mirror_surface_path("app/core/middleware.py") is False


def test_plans_commit_whitelist_boundaries() -> None:
    assert is_plans_commit_whitelisted("TODO.md") is True
    assert is_plans_commit_whitelisted("docs/plan/a.md") is True
    assert is_plans_commit_whitelisted("docs/planner/a.md") is False


def test_destructive_git_command_is_denied(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    service = NightlyRepoSyncService(repo)

    assert _is_destructive_git_command(["reset", "--hard"]) is True
    result = service._run_git(repo, "reset", "--hard")

    assert result.status == "blocked"
    assert result.block_reason == BLOCK_VERIFICATION_FAILED


def test_main_diverged_resolves_in_sync_worktree_then_pushes(tmp_path: Path) -> None:
    repo = _init_repo_with_origin(tmp_path)
    other = _clone_origin(repo, tmp_path)

    (repo / "local.txt").write_text("local\n", encoding="utf-8")
    _git(repo, "add", "local.txt")
    _git(repo, "commit", "-m", "local change")

    (other / "remote.txt").write_text("remote\n", encoding="utf-8")
    _git(other, "add", "remote.txt")
    _git(other, "commit", "-m", "remote change")
    _git(other, "push", "origin", "main")
    _git(repo, "fetch", "origin")

    result = NightlyRepoSyncService(repo, sync_stamp="20260508-030000").resolve_main_divergence()

    assert result.status == "ok"
    assert result.stage == "main_merge_push"
    assert (repo / "local.txt").read_text(encoding="utf-8") == "local\n"
    assert (repo / "remote.txt").read_text(encoding="utf-8") == "remote\n"
    assert not (repo / ".worktrees" / "nightly-main-sync-20260508-030000").exists()

    remote_head = subprocess.run(
        ["git", "rev-parse", "origin/main"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    local_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert remote_head == local_head


def test_main_diverged_mirror_conflict_blocks_without_push(tmp_path: Path) -> None:
    repo = _init_repo_with_origin(tmp_path)
    (repo / ".agents").mkdir()
    (repo / ".agents" / "skill.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".agents/skill.md")
    _git(repo, "commit", "-m", "add mirror file")
    _git(repo, "push", "origin", "main")
    other = _clone_origin(repo, tmp_path)

    (repo / ".agents" / "skill.md").write_text("local\n", encoding="utf-8")
    _git(repo, "add", ".agents/skill.md")
    _git(repo, "commit", "-m", "local mirror change")

    (other / ".agents" / "skill.md").write_text("remote\n", encoding="utf-8")
    _git(other, "add", ".agents/skill.md")
    _git(other, "commit", "-m", "remote mirror change")
    _git(other, "push", "origin", "main")
    _git(repo, "fetch", "origin")
    before_remote = subprocess.run(
        ["git", "rev-parse", "origin/main"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    result = NightlyRepoSyncService(repo, sync_stamp="20260508-040000").resolve_main_divergence()

    assert result.status == "blocked"
    assert result.block_reason == BLOCK_MIRROR_CONFLICT
    assert not (repo / ".worktrees" / "nightly-main-sync-20260508-040000").exists()
    assert subprocess.run(
        ["git", "rev-parse", "origin/main"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == before_remote
