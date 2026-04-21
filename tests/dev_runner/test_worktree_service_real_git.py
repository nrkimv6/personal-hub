"""worktree_service 실제 git 통합 테스트"""

import os
import subprocess
from pathlib import Path

import pytest

from app.modules.dev_runner.services.worktree_service import get_all_worktrees, get_all_worktrees_full


def _run_git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", *args], cwd=str(repo), capture_output=True, check=True, env=env)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "test@test.com")
    _run_git(repo, "config", "user.name", "Test")
    _run_git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("seed", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-m", "init")
    return repo


def _commit_file(repo: Path, path: str, content: bytes | str, message: str, date: str, binary: bool = False) -> None:
    file_path = repo / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        file_path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    else:
        file_path.write_text(content if isinstance(content, str) else content.decode("utf-8"), encoding="utf-8")
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = date
    env["GIT_COMMITTER_DATE"] = date
    _run_git(repo, "add", path, env=env)
    _run_git(repo, "commit", "-m", message, env=env)


@pytest.mark.asyncio
async def test_get_all_worktrees_real_repo_basic(tmp_path: Path):
    repo = _init_repo(tmp_path)
    worktree_path = repo / ".worktrees" / "impl-foo"
    _run_git(repo, "worktree", "add", "-b", "impl/foo", str(worktree_path))

    _commit_file(
        worktree_path,
        "app/foo.py",
        "print('hello')\n",
        "feat: add foo",
        "2026-04-07T08:00:00+0900",
    )

    plan_dir = repo / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "2026-04-07_impl-foo.md").write_text("> branch: impl/foo\n", encoding="utf-8")

    result = await get_all_worktrees_full(repo_root=repo)

    assert len(result) == 1
    worktree = result[0]
    assert worktree.branch == "impl/foo"
    assert worktree.ahead == 1
    assert worktree.behind == 0
    assert worktree.plan_file.replace("\\", "/") == "docs/plan/2026-04-07_impl-foo.md"
    assert len(worktree.commits) == 1


@pytest.mark.asyncio
async def test_get_all_worktrees_real_repo_binary_commit(tmp_path: Path):
    repo = _init_repo(tmp_path)
    worktree_path = repo / ".worktrees" / "impl-binary"
    _run_git(repo, "worktree", "add", "-b", "impl/binary", str(worktree_path))

    _commit_file(
        worktree_path,
        "app/image.bin",
        b"\x00\x01\x02\x03",
        "feat: add binary",
        "2026-04-07T09:00:00+0900",
        binary=True,
    )

    result = await get_all_worktrees_full(repo_root=repo)

    assert result[0].commits[0].diff_stat[0].changes == "- -"


@pytest.mark.asyncio
async def test_get_all_worktrees_real_repo_oldest_commit_used_for_created_at(tmp_path: Path):
    repo = _init_repo(tmp_path)
    worktree_path = repo / ".worktrees" / "impl-dates"
    _run_git(repo, "worktree", "add", "-b", "impl/dates", str(worktree_path))

    _commit_file(
        worktree_path,
        "app/first.py",
        "print('first')\n",
        "feat: first",
        "2026-04-07 08:00:00 +0900",
    )
    _commit_file(
        worktree_path,
        "app/second.py",
        "print('second')\n",
        "feat: second",
        "2026-04-07 10:00:00 +0900",
    )

    result = await get_all_worktrees(repo_root=repo)

    assert result.worktrees[0].created_at == "2026-04-07 08:00:00 +0900"
    assert result.worktrees[0].commit_count == 2
