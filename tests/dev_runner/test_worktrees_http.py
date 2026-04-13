"""GET /api/v1/dev-runner/worktrees HTTP 통합 테스트 (T5)"""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.modules.dev_runner.schemas import (
    MainDirtyStatus,
    WorktreeInfo,
    WorktreeListResponse,
)

pytestmark = [pytest.mark.http, pytest.mark.asyncio]

_MOCK_WORKTREE_INFO = WorktreeInfo(
    branch="impl/test-branch",
    worktree_path="/repo/.worktrees/impl-test",
    created_at="2026-04-07 10:00:00 +0900",
    ahead=2,
    behind=0,
    locked=False,
    commits=[],
    plan_file="docs/plan/2026-04-07_test.md",
    plan_mtime="2026-04-07T10:00:00",
)

_MOCK_RESPONSE = WorktreeListResponse(
    worktrees=[_MOCK_WORKTREE_INFO],
    plan_only=[],
    branch_unresolved=[],
    main_dirty=MainDirtyStatus(),
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_get_worktrees_returns_list(client):
    """GET /api/v1/dev-runner/worktrees → 200, 리스트, 필수 필드 존재"""
    with patch(
        "app.modules.dev_runner.routes.worktrees.get_all_worktrees",
        new=AsyncMock(return_value=_MOCK_RESPONSE),
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


async def test_worktree_list_v1_still_list(client):
    """v1 엔드포인트는 항상 list 타입 응답 유지"""
    with patch(
        "app.modules.dev_runner.routes.worktrees.get_all_worktrees",
        new=AsyncMock(return_value=_MOCK_RESPONSE),
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees")

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_worktree_list_v2_response_has_all_keys(client):
    """GET /api/v1/dev-runner/worktrees/v2 → object, 필수 키 존재"""
    with patch(
        "app.modules.dev_runner.routes.worktrees.get_all_worktrees",
        new=AsyncMock(return_value=_MOCK_RESPONSE),
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


async def test_worktree_v2_plan_mtime_present(client):
    """v2 응답의 worktrees[0]에 plan_mtime이 ISO 형식 문자열로 존재"""
    with patch(
        "app.modules.dev_runner.routes.worktrees.get_all_worktrees",
        new=AsyncMock(return_value=_MOCK_RESPONSE),
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2")

    assert resp.status_code == 200
    data = resp.json()
    item = data["worktrees"][0]
    assert "plan_mtime" in item
    assert item["plan_mtime"] is not None
    assert item["plan_mtime"][4] == "-"  # ISO 8601 형식 간이 확인
