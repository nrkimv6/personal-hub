"""worktree list v2 live smoke tests."""

import httpx
import pytest

from tests.dev_runner.live_http_readiness import live_get_after_readiness

pytestmark = [pytest.mark.e2e, pytest.mark.http_live]

BASE_URL = "http://localhost:8001"


def _get(path: str) -> httpx.Response:
    return live_get_after_readiness(path, base_url=BASE_URL)


def test_worktree_list_v2_live_shape_smoke():
    resp = _get("/api/v1/dev-runner/worktrees/v2")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "worktrees" in data
    assert "plan_only" in data
    assert "branch_unresolved" in data
    assert "main_dirty" in data


def test_worktree_list_v2_live_worktree_counts_match_v1():
    v1_resp = _get("/api/v1/dev-runner/worktrees")
    v2_resp = _get("/api/v1/dev-runner/worktrees/v2")

    assert v1_resp.status_code == 200
    assert v2_resp.status_code == 200

    v1_data = v1_resp.json()
    v2_data = v2_resp.json()

    assert isinstance(v1_data, list)
    assert isinstance(v2_data["worktrees"], list)
    assert len(v2_data["worktrees"]) == len(v1_data)
