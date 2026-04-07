"""GET /api/v1/dev-runner/worktrees HTTP 통합 테스트 (T5)"""
import pytest
from unittest.mock import AsyncMock, patch
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


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_get_worktrees_returns_list(client):
    """GET /api/v1/dev-runner/worktrees → 200, 리스트, 필수 필드 존재"""
    with patch(
        "app.modules.dev_runner.services.worktree_service.get_all_worktrees",
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
