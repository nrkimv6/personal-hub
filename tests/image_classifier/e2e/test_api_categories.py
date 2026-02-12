"""카테고리 API 엔드포인트 테스트"""
import pytest
from sqlalchemy import text


# ================================================
# Right: 기본 CRUD 동작
# ================================================

def test_create_root_category(client, test_db):
    """5.1 Right: 부모 없는 루트 카테고리 생성"""
    response = client.post("/api/ic/categories/", json={
        "name": "여행",
        "parent_id": None,
        "importance": "high",
    })

    assert response.status_code == 200
    data = response.json()

    assert data["name"] == "여행"
    assert data["parent_id"] is None
    assert data["full_path"] == "여행"
    assert data["importance"] == "high"


def test_create_child_category(client, test_db):
    """5.2 Right: 부모 있는 자식 생성, full_path 자동 생성"""
    # 부모 생성
    parent_response = client.post("/api/ic/categories/", json={"name": "여행"})
    parent_id = parent_response.json()["id"]

    # 자식 생성
    child_response = client.post("/api/ic/categories/", json={
        "name": "제주도",
        "parent_id": parent_id,
    })

    assert child_response.status_code == 200
    child_data = child_response.json()

    assert child_data["name"] == "제주도"
    assert child_data["parent_id"] == parent_id
    assert child_data["full_path"] == "여행/제주도"


def test_get_categories_flat(client, test_db):
    """5.3 Right: include_tree=false → 플랫 리스트"""
    # 카테고리 생성
    client.post("/api/ic/categories/", json={"name": "여행"})
    client.post("/api/ic/categories/", json={"name": "음식"})

    # 플랫 리스트 조회
    response = client.get("/api/ic/categories/?include_tree=false")

    assert response.status_code == 200
    data = response.json()

    assert "categories" in data
    assert len(data["categories"]) == 2
    # children 필드는 있지만 비어있음
    assert all("children" in cat for cat in data["categories"])


def test_get_categories_tree(client, test_db):
    """5.4 Right: include_tree=true → 트리 구조"""
    # 부모 생성
    parent_response = client.post("/api/ic/categories/", json={"name": "여행"})
    parent_id = parent_response.json()["id"]

    # 자식 생성
    client.post("/api/ic/categories/", json={"name": "제주도", "parent_id": parent_id})
    client.post("/api/ic/categories/", json={"name": "부산", "parent_id": parent_id})

    # 트리 조회
    response = client.get("/api/ic/categories/?include_tree=true")

    assert response.status_code == 200
    data = response.json()

    # 루트는 1개 (여행)
    assert len(data["categories"]) == 1

    root = data["categories"][0]
    assert root["name"] == "여행"
    assert len(root["children"]) == 2

    # 자식 이름 확인 (순서 무관)
    child_names = {child["name"] for child in root["children"]}
    assert child_names == {"제주도", "부산"}


def test_update_category_name(client, test_db):
    """5.5 Right: name 변경 → full_path 자동 갱신"""
    # 카테고리 생성
    create_response = client.post("/api/ic/categories/", json={"name": "여행"})
    cat_id = create_response.json()["id"]

    # 이름 변경
    update_response = client.put(f"/api/ic/categories/{cat_id}", json={"name": "여행기록"})

    assert update_response.status_code == 200

    # DB 확인
    result = test_db.execute(
        text("SELECT name, full_path FROM categories WHERE id = :cat_id"),
        {"cat_id": cat_id}
    ).fetchone()

    assert result.name == "여행기록"
    assert result.full_path == "여행기록"


def test_update_cascades_to_children(client, test_db):
    """5.6 Right: 부모 이름 변경 → 자식 full_path도 갱신"""
    # 부모 생성
    parent_response = client.post("/api/ic/categories/", json={"name": "여행"})
    parent_id = parent_response.json()["id"]

    # 자식 생성
    child_response = client.post("/api/ic/categories/", json={"name": "제주도", "parent_id": parent_id})
    child_id = child_response.json()["id"]

    # 부모 이름 변경
    client.put(f"/api/ic/categories/{parent_id}", json={"name": "여행기록"})

    # 자식 full_path 확인
    child_result = test_db.execute(
        text("SELECT full_path FROM categories WHERE id = :cat_id"),
        {"cat_id": child_id}
    ).fetchone()

    assert child_result.full_path == "여행기록/제주도"


def test_delete_leaf_category(client, test_db):
    """5.7 Right: 자식 없는 카테고리 삭제"""
    # 카테고리 생성
    create_response = client.post("/api/ic/categories/", json={"name": "여행"})
    cat_id = create_response.json()["id"]

    # 삭제
    delete_response = client.delete(f"/api/ic/categories/{cat_id}")

    assert delete_response.status_code == 200

    # DB 확인 (삭제됨)
    result = test_db.execute(
        text("SELECT COUNT(*) FROM categories WHERE id = :cat_id"),
        {"cat_id": cat_id}
    ).fetchone()

    assert result[0] == 0


# ================================================
# Boundary: 경계 조건
# ================================================

def test_create_duplicate_fullpath(client, test_db):
    """5.8 Boundary: 중복 full_path → 409 에러"""
    # 첫 번째 생성
    client.post("/api/ic/categories/", json={"name": "여행"})

    # 중복 생성 시도
    duplicate_response = client.post("/api/ic/categories/", json={"name": "여행"})

    assert duplicate_response.status_code == 409
    assert "이미 존재하는 카테고리 경로" in duplicate_response.json()["detail"]


def test_create_with_all_optional_fields(client, test_db):
    """5.9 Boundary: 모든 선택 필드 포함 생성"""
    response = client.post("/api/ic/categories/", json={
        "name": "여행",
        "importance": "high",
        "target_folder_template": "D:/Photos/{year}/{category}",
        "description": "여행 관련 사진"
    })

    assert response.status_code == 200
    data = response.json()

    assert data["importance"] == "high"
    assert data["target_folder_template"] == "D:/Photos/{year}/{category}"
    assert data["description"] == "여행 관련 사진"


# ================================================
# Error: 예외 조건
# ================================================

def test_create_invalid_parent(client, test_db):
    """5.10 Error: parent_id=9999 → 404"""
    response = client.post("/api/ic/categories/", json={
        "name": "제주도",
        "parent_id": 9999
    })

    assert response.status_code == 404
    assert "부모 카테고리를 찾을 수 없습니다" in response.json()["detail"]


def test_delete_with_children_no_force(client, test_db):
    """5.11 Error: 자식 있고 force=false → 400"""
    # 부모 생성
    parent_response = client.post("/api/ic/categories/", json={"name": "여행"})
    parent_id = parent_response.json()["id"]

    # 자식 생성
    client.post("/api/ic/categories/", json={"name": "제주도", "parent_id": parent_id})

    # force 없이 삭제 시도
    delete_response = client.delete(f"/api/ic/categories/{parent_id}")

    assert delete_response.status_code == 400
    assert "하위 카테고리가" in delete_response.json()["detail"]


def test_delete_with_children_force(client, test_db):
    """5.12 Error: force=true → 자식도 삭제"""
    # 부모 생성
    parent_response = client.post("/api/ic/categories/", json={"name": "여행"})
    parent_id = parent_response.json()["id"]

    # 자식 생성
    child_response = client.post("/api/ic/categories/", json={"name": "제주도", "parent_id": parent_id})
    child_id = child_response.json()["id"]

    # force=true로 삭제
    delete_response = client.delete(f"/api/ic/categories/{parent_id}?force=true")

    assert delete_response.status_code == 200

    # 부모와 자식 모두 삭제됨 확인
    parent_result = test_db.execute(
        text("SELECT COUNT(*) FROM categories WHERE id = :cat_id"),
        {"cat_id": parent_id}
    ).fetchone()

    child_result = test_db.execute(
        text("SELECT COUNT(*) FROM categories WHERE id = :cat_id"),
        {"cat_id": child_id}
    ).fetchone()

    assert parent_result[0] == 0
    assert child_result[0] == 0


def test_delete_nonexistent(client, test_db):
    """5.13 Error: 존재하지 않는 ID → 404"""
    response = client.delete("/api/ic/categories/9999")

    assert response.status_code == 404
    assert "카테고리를 찾을 수 없습니다" in response.json()["detail"]


def test_update_empty_request(client, test_db):
    """5.14 Error: 모든 필드 null → 400"""
    # 카테고리 생성
    create_response = client.post("/api/ic/categories/", json={"name": "여행"})
    cat_id = create_response.json()["id"]

    # 빈 요청으로 업데이트 시도
    update_response = client.put(f"/api/ic/categories/{cat_id}", json={})

    assert update_response.status_code == 400
    assert "수정할 내용이 없습니다" in update_response.json()["detail"]


# ================================================
# Inverse: 라이프사이클 테스트
# ================================================

def test_category_lifecycle_crud(client, test_db):
    """5.15 Inverse: 생성→조회→수정→삭제 왕복"""
    # 1. 생성
    create_response = client.post("/api/ic/categories/", json={
        "name": "여행",
        "importance": "high"
    })
    assert create_response.status_code == 200
    cat_id = create_response.json()["id"]

    # 2. 조회
    get_response = client.get("/api/ic/categories/?include_tree=false")
    assert get_response.status_code == 200
    categories = get_response.json()["categories"]
    assert any(cat["id"] == cat_id for cat in categories)

    # 3. 수정
    update_response = client.put(f"/api/ic/categories/{cat_id}", json={
        "name": "여행기록",
        "importance": "medium"
    })
    assert update_response.status_code == 200

    # 수정 확인
    result = test_db.execute(
        text("SELECT name, importance FROM categories WHERE id = :cat_id"),
        {"cat_id": cat_id}
    ).fetchone()
    assert result.name == "여행기록"
    assert result.importance == "medium"

    # 4. 삭제
    delete_response = client.delete(f"/api/ic/categories/{cat_id}")
    assert delete_response.status_code == 200

    # 삭제 확인
    count = test_db.execute(
        text("SELECT COUNT(*) FROM categories WHERE id = :cat_id"),
        {"cat_id": cat_id}
    ).fetchone()[0]
    assert count == 0
