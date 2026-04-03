"""settings API 엔드포인트 테스트"""

import httpx
from fastapi import FastAPI
import pytest

from app.modules.dev_runner.routes.settings import router as settings_router
from app.modules.dev_runner.services.settings_service import SettingsService


def _create_test_app(svc: SettingsService) -> FastAPI:
    app = FastAPI()
    # settings_service 싱글톤을 tmp 경로 svc로 교체
    import app.modules.dev_runner.routes.settings as settings_module
    settings_module.settings_service = svc
    app.include_router(settings_router, prefix="/api/v1/dev-runner/settings")
    return app


@pytest.fixture
def svc(tmp_path) -> SettingsService:
    return SettingsService(settings_file=tmp_path / "dev_runner_settings.json")


@pytest.fixture
async def client(svc):
    test_app = _create_test_app(svc)
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_settings_api_RIGHT_get(client):
    """GET 200 + 기본값 반환"""
    resp = await client.get("/api/v1/dev-runner/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "max_concurrent_runners" in data
    assert data["default_engine"] == "claude"
    assert data["default_fix_engine"] == "claude"
    assert isinstance(data["max_concurrent_runners"], int)


@pytest.mark.anyio
async def test_settings_api_RIGHT_put(client):
    """PUT 200 + 갱신값 반환"""
    resp = await client.put(
        "/api/v1/dev-runner/settings",
        json={
            "max_concurrent_runners": 5,
            "default_engine": "gemini",
            "default_fix_engine": "codex",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["max_concurrent_runners"] == 5
    assert data["default_engine"] == "gemini"
    assert data["default_fix_engine"] == "codex"
    assert data["updated_at"] is not None


@pytest.mark.anyio
async def test_settings_api_ERROR_put_invalid(client):
    """PUT 422 (범위 밖 값)"""
    resp = await client.put(
        "/api/v1/dev-runner/settings",
        json={"max_concurrent_runners": 0},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_settings_api_RIGHT_put_partial_update(client):
    """부분 업데이트 시 누락 필드는 기존값 유지"""
    resp1 = await client.put(
        "/api/v1/dev-runner/settings",
        json={"max_concurrent_runners": 6, "default_engine": "gemini", "default_fix_engine": "claude"},
    )
    assert resp1.status_code == 200

    resp2 = await client.put(
        "/api/v1/dev-runner/settings",
        json={"default_fix_engine": "cc-codex"},
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["max_concurrent_runners"] == 6
    assert data["default_engine"] == "gemini"
    assert data["default_fix_engine"] == "cc-codex"


@pytest.mark.anyio
async def test_settings_api_RIGHT_put_partial_default_engine(client):
    """default_engine만 부분 업데이트해도 다른 필드는 유지된다."""
    resp1 = await client.put(
        "/api/v1/dev-runner/settings",
        json={"max_concurrent_runners": 4, "default_engine": "claude", "default_fix_engine": "gemini"},
    )
    assert resp1.status_code == 200

    resp2 = await client.put(
        "/api/v1/dev-runner/settings",
        json={"default_engine": "cc-codex"},
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["max_concurrent_runners"] == 4
    assert data["default_engine"] == "cc-codex"
    assert data["default_fix_engine"] == "gemini"
