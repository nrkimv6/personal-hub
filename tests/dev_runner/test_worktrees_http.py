"""GET /api/v1/dev-runner/worktrees HTTP 통합 테스트 (T5)"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace
from httpx import AsyncClient, ASGITransport

from app.main import app

pytestmark = [pytest.mark.http, pytest.mark.asyncio]

_MOCK_WORKTREES = [
    {
        "branch": "impl/test-branch",
        "worktree_path": "/repo/.worktrees/impl-test",
        "created_at": "2026-04-07 10:00:00 +0900",
        "ahead": 2,
        "behind": 0,
        "locked": False,
        "commits": [],
        "plan_file": None,
    }
]

_MOCK_WORKTREE_RESPONSE = {
    "worktrees": [
        {
            "branch": "impl/test-branch",
            "worktree_path": "/repo/.worktrees/impl-test",
            "created_at": "2026-04-07 10:00:00 +0900",
            "ahead": 2,
            "behind": 0,
            "locked": False,
            "commits": [],
            "plan_file": None,
            "plan_mtime": "2026-04-07T10:00:00+09:00",
        }
    ],
    "plan_only": [],
    "branch_unresolved": [],
    "main_dirty": {
        "dirty_count": 0,
        "files": [],
    },
}


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_get_worktrees_returns_list(client):
    """GET /api/v1/dev-runner/worktrees → 200, 리스트, 필수 필드 존재"""
    with patch(
        "app.modules.dev_runner.routes.worktrees.get_all_worktrees",
        new=AsyncMock(return_value=_MOCK_WORKTREES),
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    item = data[0]
    assert "branch" in item
    assert "ahead" in item
    assert "behind" in item
    assert "commits" in item


async def test_get_worktrees_v1_still_list(client):
    with patch(
        "app.modules.dev_runner.routes.worktrees.get_all_worktrees",
        new=AsyncMock(return_value=_MOCK_WORKTREES),
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["branch"] == "impl/test-branch"


async def test_get_worktrees_v2_returns_object(client):
    with patch(
        "app.modules.dev_runner.routes.worktrees.get_all_worktrees",
        new=AsyncMock(return_value=_MOCK_WORKTREE_RESPONSE),
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "worktrees" in data
    assert "plan_only" in data
    assert "branch_unresolved" in data
    assert "main_dirty" in data
    assert isinstance(data["worktrees"], list)
    assert isinstance(data["plan_only"], list)
    assert isinstance(data["branch_unresolved"], list)
    assert isinstance(data["main_dirty"], dict)


async def test_get_worktrees_v2_plan_mtime_present(client):
    with patch(
        "app.modules.dev_runner.routes.worktrees.get_all_worktrees",
        new=AsyncMock(return_value=_MOCK_WORKTREE_RESPONSE),
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2")

    assert resp.status_code == 200
    data = resp.json()
    assert data["worktrees"][0]["plan_mtime"] is not None
    assert isinstance(data["worktrees"][0]["plan_mtime"], str)
    assert data["worktrees"][0]["plan_mtime"].startswith("2026-04-07T10:00")


async def test_get_worktrees_v2_repo_not_found_returns_404(client):
    with patch(
        "app.modules.git_repos.services.repo_service.GitRepoService.get_repo",
        new=MagicMock(return_value=None),
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2?repo_id=999999")

    assert resp.status_code == 404


async def test_worktrees_default_no_repo_id_v1(client):
    with patch(
        "app.modules.dev_runner.routes.worktrees.get_all_worktrees",
        new=AsyncMock(return_value=_MOCK_WORKTREES),
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees")

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_worktrees_v1_repo_not_found_returns_404(client):
    with patch(
        "app.modules.git_repos.services.repo_service.GitRepoService.get_repo",
        new=MagicMock(return_value=None),
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees?repo_id=999999")

    assert resp.status_code == 404


async def test_worktrees_repos_list_returns_array(client):
    repos = [
        SimpleNamespace(id=1, alias="monitor-page", path="/repo/monitor-page"),
        SimpleNamespace(id=2, alias="wtools", path="D:/work/project/service/wtools"),
    ]

    with patch(
        "app.modules.git_repos.services.repo_service.GitRepoService.list_repos",
        return_value=repos,
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees/repos")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["id"] == 1
    assert data[1]["alias"] == "wtools"
