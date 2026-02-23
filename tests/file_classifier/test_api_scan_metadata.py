"""메타데이터 스캔 API 테스트"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.modules.file_classifier.routers.scan import router as scan_router
from app.modules.file_classifier.database import get_db


@pytest.fixture
def meta_client(test_db):
    app = FastAPI()
    app.include_router(scan_router, prefix="/api/fc")

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c


def test_metadata_start(meta_client):
    """메타데이터 추출 시작 엔드포인트"""
    resp = meta_client.post("/api/fc/scan/metadata/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("started", "already_running")


def test_metadata_status(meta_client):
    """메타데이터 추출 상태 조회"""
    resp = meta_client.get("/api/fc/scan/metadata/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_running" in data
    assert "total" in data
    assert "processed" in data
