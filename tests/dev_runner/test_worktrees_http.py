"""GET /api/v1/dev-runner/worktrees HTTP 통합 테스트 — main 머지 후 실행 (T5)

⚠️ 이 파일은 /merge-test에서 main 머지 후 실행한다. 워크트리 내에서 직접 실행 금지.
"""
import pytest

pytestmark = pytest.mark.http


@pytest.fixture
def client():
    import fakeredis
    import fakeredis.aioredis
    from unittest.mock import patch, AsyncMock
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.modules.dev_runner.routes import router

    app = FastAPI()
    app.include_router(router)

    with (
        patch("app.core.redis_client.get_redis", return_value=fakeredis.FakeRedis()),
        patch(
            "app.modules.dev_runner.services.worktree_service.get_all_worktrees",
            new=AsyncMock(return_value=[
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
            ]),
        ),
    ):
        yield TestClient(app)


def test_get_worktrees_returns_list(client):
    """GET /api/v1/dev-runner/worktrees → 200, 리스트, 필수 필드 존재"""
    resp = client.get("/api/v1/dev-runner/worktrees")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    item = data[0]
    assert "branch" in item
    assert "ahead" in item
    assert "behind" in item
    assert "commits" in item
