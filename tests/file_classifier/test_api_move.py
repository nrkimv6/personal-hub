"""이동 API 테스트"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.modules.file_classifier.routers.move import router as move_router
from app.modules.file_classifier.database import get_db


@pytest.fixture
def move_client(test_db):
    app = FastAPI()
    app.include_router(move_router, prefix="/api/fc")

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c


def test_move_preview_empty(move_client):
    """승인된 파일 없으면 빈 리스트 반환"""
    resp = move_client.post("/api/fc/move/preview", json={})
    assert resp.status_code == 200
    data = resp.json()
    # TARGET_ROOT_FOLDER가 없으면 빈 items
    assert "items" in data


def test_move_status(move_client):
    """이동 통계 조회"""
    resp = move_client.get("/api/fc/move/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "moved" in data
    assert "pending_move" in data


def test_undo_nonexistent(move_client):
    """존재하지 않는 파일 되돌리기"""
    resp = move_client.post("/api/fc/move/undo/99999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
