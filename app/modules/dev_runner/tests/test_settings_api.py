"""settings API 엔드포인트 테스트"""

import pytest
import httpx
from pathlib import Path
from fastapi import FastAPI
from unittest.mock import patch

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
    assert isinstance(data["max_concurrent_runners"], int)


@pytest.mark.anyio
async def test_settings_api_RIGHT_put(client):
    """PUT 200 + 갱신값 반환"""
    resp = await client.put(
        "/api/v1/dev-runner/settings",
        json={"max_concurrent_runners": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["max_concurrent_runners"] == 5
    assert data["updated_at"] is not None


@pytest.mark.anyio
async def test_settings_api_ERROR_put_invalid(client):
    """PUT 422 (범위 밖 값)"""
    resp = await client.put(
        "/api/v1/dev-runner/settings",
        json={"max_concurrent_runners": 0},
    )
    assert resp.status_code == 422
