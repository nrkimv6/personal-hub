"""diagnostics 엔드포인트 HTTP 통합 테스트"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app

pytestmark = [pytest.mark.http, pytest.mark.asyncio]


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_diagnostics_http_right_200(client):
    """GET /api/v1/dev-runner/logs/diagnostics → 200, body에 steps 배열 포함."""
    resp = await client.get("/api/v1/dev-runner/logs/diagnostics")
    assert resp.status_code == 200
    data = resp.json()
    assert "steps" in data
    assert isinstance(data["steps"], list)


async def test_diagnostics_http_right_steps_structure(client):
    """각 step에 step, name, ok, detail 키 존재."""
    resp = await client.get("/api/v1/dev-runner/logs/diagnostics")
    assert resp.status_code == 200
    steps = resp.json()["steps"]
    assert len(steps) >= 1
    for s in steps:
        assert "step" in s
        assert "name" in s
        assert "ok" in s
        assert "detail" in s
