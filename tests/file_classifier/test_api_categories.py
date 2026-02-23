"""카테고리 API 테스트"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.modules.file_classifier.routers.categories import router as categories_router
from app.modules.file_classifier.database import get_db


@pytest.fixture
def categories_client(test_db):
    app = FastAPI()
    app.include_router(categories_router, prefix="/api/fc")

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c


def test_list_categories_empty(categories_client):
    resp = categories_client.get("/api/fc/categories")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_root_category(categories_client):
    resp = categories_client.post("/api/fc/categories", json={
        "name": "test_root_unique",
        "sort_order": 999
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["full_path"] == "test_root_unique"


def test_create_child_category(categories_client, test_db):
    # 루트 생성 (고유 이름 사용)
    root_resp = categories_client.post("/api/fc/categories", json={"name": "test_video_new", "sort_order": 299})
    root_id = root_resp.json()["id"]

    # 자식 생성
    child_resp = categories_client.post("/api/fc/categories", json={
        "name": "testmovie",
        "parent_id": root_id,
        "sort_order": 1
    })
    assert child_resp.status_code == 200
    assert child_resp.json()["full_path"] == "test_video_new/testmovie"


def test_delete_with_children_fails(categories_client, test_db):
    # 부모 생성
    parent_resp = categories_client.post("/api/fc/categories", json={"name": "testdocs_unique", "sort_order": 599})
    parent_id = parent_resp.json()["id"]

    # 자식 생성
    categories_client.post("/api/fc/categories", json={"name": "testpdf", "parent_id": parent_id})

    # 부모 삭제 시도 → 400
    del_resp = categories_client.delete(f"/api/fc/categories/{parent_id}")
    assert del_resp.status_code == 400


def test_get_category_files(categories_client, test_db):
    cat_resp = categories_client.post("/api/fc/categories", json={"name": "misc_test_files_unique", "sort_order": 999})
    cat_id = cat_resp.json()["id"]

    test_db.execute(text(
        "INSERT INTO fc_files (file_path, file_name, extension, file_size, file_group, rule_category_id) "
        "VALUES ('/test/f.dat', 'f.dat', '.dat', 100, 'misc', :cat_id)"
    ), {"cat_id": cat_id})
    test_db.commit()

    resp = categories_client.get(f"/api/fc/categories/{cat_id}/files")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
