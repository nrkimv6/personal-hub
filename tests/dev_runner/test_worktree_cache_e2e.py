"""worktree list cache live smoke tests."""

import httpx
import pytest

from tests.dev_runner.live_http_readiness import live_get_after_readiness

pytestmark = [pytest.mark.e2e, pytest.mark.http_live]

BASE_URL = "http://localhost:8001"


def _assert_worktree_list_shape(data: dict) -> None:
    worktrees = data.get("worktrees", [])
    assert isinstance(worktrees, list)
    for key in ("plan_only", "branch_unresolved", "main_dirty"):
        assert key in data


def _get(path: str) -> httpx.Response:
    return live_get_after_readiness(path, base_url=BASE_URL)


def test_worktree_list_v2_cache_live_returns_shape_on_repeat():
    first = _get("/api/v1/dev-runner/worktrees/v2")
    second = _get("/api/v1/dev-runner/worktrees/v2")

    assert first.status_code == 200
    assert second.status_code == 200
    _assert_worktree_list_shape(first.json())
    _assert_worktree_list_shape(second.json())


def test_worktree_list_v2_cache_live_force_refresh_returns_200():
    forced = _get("/api/v1/dev-runner/worktrees/v2?force=1")

    assert forced.status_code == 200
    data = forced.json()
    assert isinstance(data, dict)
    assert "worktrees" in data
