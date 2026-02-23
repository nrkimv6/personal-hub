"""분류 API 테스트"""
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.modules.file_classifier.routers.classify import router as classify_router
from app.modules.file_classifier.database import get_db


@pytest.fixture
def classify_client(test_db):
    app = FastAPI()
    app.include_router(classify_router, prefix="/api/fc")

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c


def test_rule_start(classify_client):
    resp = classify_client.post("/api/fc/classify/rule/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("started", "already_running")


def test_classify_status(classify_client):
    resp = classify_client.get("/api/fc/classify/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_running" in data


def test_approve(classify_client, test_db):
    test_db.execute(text(
        "INSERT INTO fc_files (id, file_path, file_name, extension, file_size, file_group, status) "
        "VALUES (400, '/test/file.pdf', 'file.pdf', '.pdf', 1024, 'document', 'rule_classified')"
    ))
    test_db.execute(text(
        "INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES ('pdf', NULL, 'document/pdf', 1)"
    ))
    test_db.commit()

    cat_id = test_db.execute(text("SELECT id FROM fc_categories WHERE full_path = 'document/pdf'")).fetchone()[0]
    resp = classify_client.post("/api/fc/classify/approve", json={"file_ids": [400], "category_id": cat_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
