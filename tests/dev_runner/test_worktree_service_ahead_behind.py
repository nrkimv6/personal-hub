"""get_ahead_behind 계열 단위 테스트"""

import pytest
from unittest.mock import AsyncMock, patch

from app.modules.dev_runner.services.worktree_service import get_ahead_behind, get_ahead_behind_map


@pytest.mark.asyncio
async def test_get_ahead_behind_right_left_right_parse():
    with patch(
        "app.modules.dev_runner.services.worktree_service._run_git",
        new=AsyncMock(return_value="3\t7"),
    ):
        ahead, behind = await get_ahead_behind("impl/foo")

    assert ahead == 7
    assert behind == 3


@pytest.mark.asyncio
async def test_get_ahead_behind_boundary_empty_output():
    with patch(
        "app.modules.dev_runner.services.worktree_service._run_git",
        new=AsyncMock(return_value=""),
    ):
        ahead, behind = await get_ahead_behind("impl/foo")

    assert ahead == 0
    assert behind == 0


@pytest.mark.asyncio
async def test_get_ahead_behind_error_malformed_output():
    with patch(
        "app.modules.dev_runner.services.worktree_service._run_git",
        new=AsyncMock(return_value="abc\txyz"),
    ):
        ahead, behind = await get_ahead_behind("impl/foo")

    assert ahead == 0
    assert behind == 0


@pytest.mark.asyncio
async def test_get_ahead_behind_map_right_parse():
    with patch(
        "app.modules.dev_runner.services.worktree_service._run_git",
        new=AsyncMock(return_value="impl/foo|3 7\nimpl/bar|0 0"),
    ):
        result = await get_ahead_behind_map(["impl/foo", "impl/bar"])

    assert result == {
        "impl/foo": (3, 7),
        "impl/bar": (0, 0),
    }


@pytest.mark.asyncio
async def test_get_ahead_behind_map_boundary_empty_output():
    with patch(
        "app.modules.dev_runner.services.worktree_service._run_git",
        new=AsyncMock(return_value=""),
    ):
        result = await get_ahead_behind_map(["impl/foo"])

    assert result == {}


@pytest.mark.asyncio
async def test_get_ahead_behind_map_error_skips_malformed_rows():
    with patch(
        "app.modules.dev_runner.services.worktree_service._run_git",
        new=AsyncMock(return_value="impl/foo|3 7\nbad-row\nimpl/bar|abc xyz"),
    ):
        result = await get_ahead_behind_map(["impl/foo", "impl/bar"])

    assert result == {
        "impl/foo": (3, 7),
    }
