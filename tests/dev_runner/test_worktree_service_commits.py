"""get_worktree_commits 단위 테스트"""

import pytest
from unittest.mock import AsyncMock, patch

from app.modules.dev_runner.services.worktree_service import get_worktree_commits


@pytest.mark.asyncio
async def test_get_worktree_commits_right_single_log_call():
    log_output = (
        "__WT_COMMIT__abc1234567890|2026-04-07 11:00:00 +0900|feat: first\n"
        "5\t2\tapp/foo.py\n"
        "\n"
        "__WT_COMMIT__def1234567890|2026-04-07 10:00:00 +0900|feat: second | pipes\n"
        "3\t1\tapp/bar.py\n"
        "1\t0\tapp/baz.py\n"
        "\n"
        "__WT_COMMIT__ghi1234567890|2026-04-07 09:00:00 +0900|feat: third\n"
    )

    run_git = AsyncMock(return_value=log_output)
    with patch("app.modules.dev_runner.services.worktree_service._run_git", new=run_git):
        commits = await get_worktree_commits("impl/foo")

    assert run_git.await_count == 1
    assert [commit.hash for commit in commits] == [
        "abc1234567890",
        "def1234567890",
        "ghi1234567890",
    ]
    assert commits[1].message == "feat: second | pipes"
    assert [stat.file for stat in commits[1].diff_stat] == ["app/bar.py", "app/baz.py"]


@pytest.mark.asyncio
async def test_get_worktree_commits_boundary_empty_branch():
    run_git = AsyncMock(return_value="")
    with patch("app.modules.dev_runner.services.worktree_service._run_git", new=run_git):
        commits = await get_worktree_commits("impl/empty")

    assert commits == []
    assert run_git.await_count == 1


@pytest.mark.asyncio
async def test_get_worktree_commits_correct_oldest_commit_remains_last():
    log_output = (
        "__WT_COMMIT__new1234567890|2026-04-07 11:00:00 +0900|feat: newest\n"
        "__WT_COMMIT__old1234567890|2026-04-07 08:00:00 +0900|feat: oldest\n"
    )

    with patch(
        "app.modules.dev_runner.services.worktree_service._run_git",
        new=AsyncMock(return_value=log_output),
    ):
        commits = await get_worktree_commits("impl/foo")

    assert commits[-1].hash == "old1234567890"
    assert commits[-1].date == "2026-04-07 08:00:00 +0900"


@pytest.mark.asyncio
async def test_get_worktree_commits_binary_diff_preserved():
    log_output = (
        "__WT_COMMIT__abc1234567890|2026-04-07 11:00:00 +0900|feat: binary\n"
        "-\t-\tapp/image.png\n"
    )

    with patch(
        "app.modules.dev_runner.services.worktree_service._run_git",
        new=AsyncMock(return_value=log_output),
    ):
        commits = await get_worktree_commits("impl/foo")

    assert commits[0].diff_stat[0].file == "app/image.png"
    assert commits[0].diff_stat[0].changes == "- -"


@pytest.mark.asyncio
async def test_get_worktree_commits_performance_100commits_single_call():
    lines = []
    for i in range(100):
        lines.append(f"__WT_COMMIT__hash{i:03d}|2026-04-07 10:00:{i:02d} +0900|feat: commit {i}")
        lines.append(f"{i}\t0\tapp/file{i}.py")
    run_git = AsyncMock(return_value="\n".join(lines))

    with patch("app.modules.dev_runner.services.worktree_service._run_git", new=run_git):
        commits = await get_worktree_commits("impl/foo")

    assert len(commits) == 100
    assert run_git.await_count == 1
