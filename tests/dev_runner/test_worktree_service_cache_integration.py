import os
import subprocess
from pathlib import Path

import pytest

from app.modules.dev_runner.services.worktree_service import get_all_worktrees


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        env=env,
    )


def _init_repo(tmp_path: Path, branch: str, commit_count: int) -> tuple[Path, Path]:
    repo = tmp_path / branch.replace("/", "-")
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")

    plan_dir = repo / "docs" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    worktree = repo / ".worktrees" / branch.replace("/", "-")
    _git(repo, "worktree", "add", "-b", branch, str(worktree))

    for index in range(commit_count):
        _commit(worktree, index)

    (plan_dir / f"{branch.replace('/', '-')}.md").write_text(f"> branch: {branch}\n", encoding="utf-8")
    return repo, worktree


def _commit(worktree: Path, index: int) -> None:
    target = worktree / "app" / f"feature_{index}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"print({index})\n", encoding="utf-8")
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = f"2026-04-21 0{index + 1}:00:00 +0900"
    env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"]
    _git(worktree, "add", str(target.relative_to(worktree)), env=env)
    _git(worktree, "commit", "-m", f"feat: commit {index}", env=env)


@pytest.mark.asyncio
async def test_cache_integration_same_repo_hit_returns_cached_response(tmp_path: Path):
    repo, worktree = _init_repo(tmp_path, "impl/cache-hit", 1)

    first = await get_all_worktrees(repo_root=repo, use_cache=True, cache_repo_id=7)
    _commit(worktree, 1)
    second = await get_all_worktrees(repo_root=repo, use_cache=True, cache_repo_id=7)

    assert first.worktrees[0].commit_count == 1
    assert second.worktrees[0].commit_count == 1


@pytest.mark.asyncio
async def test_cache_integration_repo_root_isolated_even_same_repo_id(tmp_path: Path):
    repo_a, _ = _init_repo(tmp_path, "impl/repo-a", 1)
    repo_b, _ = _init_repo(tmp_path, "impl/repo-b", 2)

    first = await get_all_worktrees(repo_root=repo_a, use_cache=True, cache_repo_id=3)
    second = await get_all_worktrees(repo_root=repo_b, use_cache=True, cache_repo_id=3)

    assert first.worktrees[0].commit_count == 1
    assert second.worktrees[0].commit_count == 2


@pytest.mark.asyncio
async def test_cache_integration_force_refresh_replaces_stale_value(tmp_path: Path):
    repo, worktree = _init_repo(tmp_path, "impl/force-refresh", 1)

    first = await get_all_worktrees(repo_root=repo, use_cache=True, cache_repo_id=11)
    _commit(worktree, 1)
    forced = await get_all_worktrees(
        repo_root=repo,
        use_cache=True,
        cache_repo_id=11,
        force=True,
    )

    assert first.worktrees[0].commit_count == 1
    assert forced.worktrees[0].commit_count == 2
