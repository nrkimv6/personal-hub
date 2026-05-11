"""diagnostics 엔드포인트 HTTP 통합 테스트"""
import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = [pytest.mark.http, pytest.mark.asyncio]


@pytest.fixture
async def client():
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def fixed_diagnostics(monkeypatch):
    from app.modules.dev_runner.routes import logs

    monkeypatch.setattr(
        logs.diagnostics_service,
        "run_diagnostics",
        lambda: {
            "steps": [
                {"step": 1, "name": "Redis 연결", "ok": True, "detail": "연결됨"},
                {"step": 9, "name": "runner DB mirror drift", "ok": True, "detail": "redis_only=0, db_only=0"},
            ]
        },
    )


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


async def test_diagnostics_http_right_includes_runner_db_mirror_drift(client):
    """GET /logs/diagnostics includes the Postgres mirror drift step."""
    resp = await client.get("/api/v1/dev-runner/logs/diagnostics")
    assert resp.status_code == 200

    steps = resp.json()["steps"]
    drift_step = next(s for s in steps if s["name"] == "runner DB mirror drift")
    assert drift_step["step"] == 9
    assert "redis_only=0" in drift_step["detail"]
    assert "db_only=0" in drift_step["detail"]
