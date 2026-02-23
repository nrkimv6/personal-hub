"""규칙 CRUD API 테스트"""
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.modules.file_classifier.routers.rules import router as rules_router
from app.modules.file_classifier.database import get_db


@pytest.fixture
def rules_client(test_db):
    # 카테고리 시드
    test_db.execute(text(
        "INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES ('misc', NULL, 'misc', 80)"
    ))
    test_db.commit()

    app = FastAPI()
    app.include_router(rules_router, prefix="/api/fc")

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c


def test_list_rules_empty(rules_client):
    resp = rules_client.get("/api/fc/rules")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_rule(rules_client, test_db):
    cat_id = test_db.execute(text("SELECT id FROM fc_categories WHERE full_path = 'misc'")).fetchone()[0]
    resp = rules_client.post("/api/fc/rules", json={
        "rule_type": "extension",
        "category_id": cat_id,
        "rule_content": {"value": ".dat"},
        "priority": 50
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "created"
    assert "id" in data


def test_toggle_rule(rules_client, test_db):
    cat_id = test_db.execute(text("SELECT id FROM fc_categories WHERE full_path = 'misc'")).fetchone()[0]
    create_resp = rules_client.post("/api/fc/rules", json={
        "rule_type": "extension",
        "category_id": cat_id,
        "rule_content": {"value": ".tmp"},
        "priority": 10
    })
    rule_id = create_resp.json()["id"]

    toggle_resp = rules_client.put(f"/api/fc/rules/{rule_id}/toggle")
    assert toggle_resp.status_code == 200


def test_delete_rule(rules_client, test_db):
    cat_id = test_db.execute(text("SELECT id FROM fc_categories WHERE full_path = 'misc'")).fetchone()[0]
    create_resp = rules_client.post("/api/fc/rules", json={
        "rule_type": "extension",
        "category_id": cat_id,
        "rule_content": {"value": ".del"},
        "priority": 10
    })
    rule_id = create_resp.json()["id"]

    del_resp = rules_client.delete(f"/api/fc/rules/{rule_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"
