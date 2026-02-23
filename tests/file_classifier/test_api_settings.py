"""설정 API 테스트"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.modules.file_classifier.routers.settings import router as settings_router


@pytest.fixture
def settings_client():
    app = FastAPI()
    app.include_router(settings_router, prefix="/api/fc")
    with TestClient(app) as c:
        yield c


def test_get_settings(settings_client):
    """설정 조회"""
    resp = settings_client.get("/api/fc/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "SCAN_ROOT_FOLDERS" in data
    assert "TARGET_ROOT_FOLDER" in data


def test_update_settings(settings_client):
    """설정 변경"""
    resp = settings_client.put("/api/fc/settings", json={
        "LLM_MODE": "cli",
        "DRY_RUN_DEFAULT": True
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "updated"

    # 변경 확인
    resp2 = settings_client.get("/api/fc/settings")
    data2 = resp2.json()
    assert data2["LLM_MODE"] == "cli"
