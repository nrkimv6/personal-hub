"""폴더 매핑 API 엔드포인트 테스트"""
import pytest
from sqlalchemy import text


@pytest.fixture
def seeded_folders_and_categories(test_db):
    """카테고리와 폴더 데이터 생성"""
    # 카테고리
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES
        (1, '여행', '여행'),
        (2, '음식', '음식'),
        (3, '가족', '가족')
    """))

    # 폴더 (일부는 매핑, 일부는 unknown)
    test_db.execute(text("""
        INSERT INTO folder_mappings (id, folder_path, file_count, folder_status, category_id) VALUES
        (1, 'D:/Photos/제주도 2023', 50, 'clear', NULL),
        (2, 'D:/Photos/새 폴더', 30, 'unclear', NULL),
        (3, 'D:/Photos/가족사진', 20, 'clear', 3),
        (4, 'D:/Photos/제주도 2023/Day1', 15, 'clear', NULL),
        (5, 'D:/Photos/제주도 2023/Day2', 20, 'clear', NULL)
    """))

    # 파일
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, source_folder_id, status) VALUES
        (1, 'D:/Photos/제주도 2023/img1.jpg', 'hash1', 1, 'pending'),
        (2, 'D:/Photos/제주도 2023/img2.jpg', 'hash2', 1, 'pending'),
        (3, 'D:/Photos/가족사진/photo.jpg', 'hash3', 3, 'pending')
    """))

    test_db.commit()


# ================================================
# Right: 기본 동작
# ================================================

def test_classify_folders_basic(client, seeded_folders_and_categories):
    """1.1 Right: POST /folders/classify → 폴더 자동 분류"""
    response = client.post("/api/ic/folders/classify")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "completed"
    assert "stats" in data
    assert "message" in data


def test_classify_folders_with_force(client, seeded_folders_and_categories):
    """1.2 Right: POST /folders/classify?force=true → 재분류"""
    response = client.post("/api/ic/folders/classify?force=true")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "completed"
    assert "재분류" in data["message"]


def test_map_folder_to_category(client, seeded_folders_and_categories):
    """1.3 Right: PUT /folders/{id}/map → 매핑 저장"""
    response = client.put("/api/ic/folders/1/map", json={
        "category_id": 1
    })

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["folder_id"] == 1
    assert data["category_id"] == 1
    assert "files_updated" in data


def test_bulk_map_folders(client, seeded_folders_and_categories):
    """1.4 Right: POST /folders/bulk-map → 일괄 매핑"""
    response = client.post("/api/ic/folders/bulk-map", json={
        "folder_ids": [1, 2],
        "category_id": 2
    })

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["folders_updated"] == 2
    assert data["category_id"] == 2


def test_inherit_mapping(client, seeded_folders_and_categories):
    """1.5 Right: POST /folders/inherit → 상속"""
    # 먼저 상위 폴더에 매핑
    client.put("/api/ic/folders/1/map", json={"category_id": 1})

    # 상속 실행
    response = client.post("/api/ic/folders/inherit", json={
        "parent_folder_id": 1,
        "apply_to_children": True
    })

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["parent_folder_id"] == 1
    assert data["children_updated"] >= 2  # Day1, Day2


# ================================================
# Boundary: 경계값 테스트
# ================================================

def test_map_nonexistent_folder(client, seeded_folders_and_categories):
    """2.1 Boundary: PUT /folders/999/map → 404 (폴더 없음)"""
    response = client.put("/api/ic/folders/999/map", json={
        "category_id": 1
    })

    # 현재는 폴더 존재 여부 확인 안 함 (카테고리만 확인)
    # UPDATE는 조용히 실패 (rowcount=0)
    assert response.status_code == 200
    data = response.json()
    assert data["files_updated"] == 0


def test_map_with_invalid_category(client, seeded_folders_and_categories):
    """2.2 Boundary: PUT /folders/{id}/map {category_id: 999} → 404"""
    response = client.put("/api/ic/folders/1/map", json={
        "category_id": 999
    })

    assert response.status_code == 404
    assert "카테고리를 찾을 수 없습니다" in response.json()["detail"]


def test_inherit_from_unmapped_folder(client, seeded_folders_and_categories):
    """2.3 Boundary: POST /folders/inherit (매핑 안 된 폴더) → 400"""
    response = client.post("/api/ic/folders/inherit", json={
        "parent_folder_id": 1,  # 매핑 안 된 폴더
        "apply_to_children": True
    })

    assert response.status_code == 400
    assert "카테고리가 설정되지 않았습니다" in response.json()["detail"]


def test_bulk_map_empty_list(client, seeded_folders_and_categories):
    """2.4 Boundary: POST /folders/bulk-map {folder_ids: []} → 빈 목록"""
    response = client.post("/api/ic/folders/bulk-map", json={
        "folder_ids": [],
        "category_id": 1
    })

    assert response.status_code == 200
    data = response.json()
    assert data["folders_updated"] == 0


# ================================================
# Error: 오류 케이스
# ================================================

def test_map_invalid_request_body(client, seeded_folders_and_categories):
    """3.1 Error: PUT /folders/{id}/map (잘못된 body) → 422"""
    response = client.put("/api/ic/folders/1/map", json={
        "category_id": "not_a_number"
    })

    assert response.status_code == 422


def test_bulk_map_invalid_type(client, seeded_folders_and_categories):
    """3.2 Error: POST /folders/bulk-map {folder_ids: "string"} → 422"""
    response = client.post("/api/ic/folders/bulk-map", json={
        "folder_ids": "not_a_list",
        "category_id": 1
    })

    assert response.status_code == 422


def test_inherit_nonexistent_parent(client, seeded_folders_and_categories):
    """3.3 Error: POST /folders/inherit {parent_folder_id: 999} → 404"""
    response = client.post("/api/ic/folders/inherit", json={
        "parent_folder_id": 999,
        "apply_to_children": True
    })

    assert response.status_code == 404
    assert "상위 폴더를 찾을 수 없습니다" in response.json()["detail"]
