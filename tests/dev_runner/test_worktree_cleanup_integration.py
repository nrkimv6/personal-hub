import subprocess
import sys
from pathlib import Path

import pytest

from app.modules.dev_runner.services.worktree_service import cleanup_worktrees, get_all_worktrees
from tests.dev_runner import conftest as dev_runner_conftest
from tests.dev_runner._path_helpers import bootstrap_plan_runner_modules

try:
    import fakeredis

    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(repo),
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


def _add_worktree(repo: Path, branch: str, folder_name: str) -> Path:
    worktree = repo / ".worktrees" / folder_name
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", str(worktree), "-b", branch)
    return worktree


def _import_process_utils():
    bootstrap_plan_runner_modules()
    return sys.modules["_dr_process_utils"]


@pytest.mark.asyncio
async def test_integration_archive_plan_worktree_is_cleanable(tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "impl/archive-cleanable"
    _add_worktree(repo, branch, "archive-cleanable")
    plan_file = repo / ".worktrees" / "plans" / "docs" / "archive" / "archive-cleanable.md"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(
        "\n".join(
            [
                "# archive-cleanable",
                f"> branch: {branch}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    response = await get_all_worktrees(repo_root=repo)

    item = next(wt for wt in response.worktrees if wt.branch == branch)
    assert item.plan_file_archived is True
    assert item.cleanable is True


@pytest.mark.asyncio
async def test_integration_cleanup_removes_test_runner_worktree(tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "runner/t-t5envhdr-abcd"
    worktree = _add_worktree(repo, branch, "t-t5envhdr-abcd")

    result = await cleanup_worktrees([branch], dry_run=False, repo_root=repo)

    assert result.summary["removed"] == 1
    assert branch not in _git(repo, "worktree", "list", "--porcelain").stdout
    assert str(worktree) not in _git(repo, "worktree", "list", "--porcelain").stdout
    assert branch not in _git(repo, "branch", "--list", branch).stdout


@pytest.mark.asyncio
async def test_integration_cleanup_preserves_locked_and_ahead(tmp_path: Path):
    repo = _init_repo(tmp_path)

    locked_branch = "impl/locked-cleanup"
    locked_worktree = _add_worktree(repo, locked_branch, "locked-cleanup")
    _git(repo, "worktree", "lock", str(locked_worktree))

    ahead_branch = "impl/ahead-cleanup"
    ahead_worktree = _add_worktree(repo, ahead_branch, "ahead-cleanup")
    (ahead_worktree / "feature.txt").write_text("ahead\n", encoding="utf-8")
    _git(ahead_worktree, "add", "feature.txt")
    _git(ahead_worktree, "commit", "-m", "ahead")

    result = await cleanup_worktrees(
        [locked_branch, ahead_branch],
        dry_run=False,
        repo_root=repo,
    )

    assert result.summary["skipped"] == 2
    listed = _git(repo, "worktree", "list", "--porcelain").stdout
    assert locked_branch in listed
    assert ahead_branch in listed


@pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis 미설치")
def test_integration_force_cleanup_on_test_source_runner(tmp_path: Path):
    repo = _init_repo(tmp_path)
    runner_id = "t-xyz-1234"
    branch = f"runner/{runner_id}"
    worktree = _add_worktree(repo, branch, runner_id)
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    redis_client.set(f"plan-runner:runners:{runner_id}:status", "running")
    redis_client.set(f"plan-runner:runners:{runner_id}:trigger", "user")
    redis_client.set(f"plan-runner:runners:{runner_id}:test_source", "xyz")
    redis_client.set(f"plan-runner:runners:{runner_id}:branch", branch)
    redis_client.set(f"plan-runner:runners:{runner_id}:worktree_path", str(worktree))

    mod = _import_process_utils()
    original_project_root = mod.PROJECT_ROOT
    original_worktree_base = mod.WORKTREE_BASE_DIR
    mod.PROJECT_ROOT = repo
    mod.WORKTREE_BASE_DIR = repo / ".worktrees"
    try:
        mod._cleanup_process_state(runner_id, redis_client, reason="integration_force_cleanup")
    finally:
        mod.PROJECT_ROOT = original_project_root
        mod.WORKTREE_BASE_DIR = original_worktree_base

    assert branch not in _git(repo, "worktree", "list", "--porcelain").stdout
    assert not worktree.exists()
    assert branch not in _git(repo, "branch", "--list", branch).stdout


def test_integration_sessionfinish_removes_real_test_runner(tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "runner/t-session-cleanup"
    worktree = _add_worktree(repo, branch, "t-session-cleanup")
    real_run = subprocess.run

    def _run_in_repo(cmd, **kwargs):
        forwarded = dict(kwargs)
        forwarded["cwd"] = str(repo)
        return real_run(cmd, **forwarded)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delenv("PLAN_RUNNER_DISABLE_SESSION_CLEANUP", raising=False)
        monkeypatch.setattr(dev_runner_conftest.subprocess, "run", _run_in_repo)
        dev_runner_conftest.pytest_sessionfinish(object(), 0)

    assert branch not in _git(repo, "worktree", "list", "--porcelain").stdout
    assert not worktree.exists()
    assert branch not in _git(repo, "branch", "--list", branch).stdout
