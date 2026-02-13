"""태그 API 엔드포인트 테스트"""
import pytest
from sqlalchemy import text


@pytest.fixture
def seeded_tags(test_db):
    """태그 데이터 생성"""
    # 태그 3개 생성
    test_db.execute(text("""
        INSERT INTO tags (id, name, usage_count, created_at) VALUES
        (1, 'work', 10, '2023-01-01 10:00:00'),
        (2, 'travel', 5, '2023-01-02 11:00:00'),
        (3, 'family', 15, '2023-01-03 12:00:00')
    """))

    # 파일 생성
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status) VALUES
        (1, '/test/file1.jpg', 'hash1', 'pending'),
        (2, '/test/file2.jpg', 'hash2', 'pending')
    """))

    test_db.commit()


# ================================================
# Right: 기본 CRUD 동작
# ================================================

def test_get_tags_sort_by_usage(client, seeded_tags):
    """15.1 Right: GET /tags?sort_by=usage → usage_count DESC"""
    response = client.get("/api/ic/tags/?sort_by=usage&limit=100")

    assert response.status_code == 200
    data = response.json()

    assert "tags" in data
    assert len(data["tags"]) == 3

    # usage_count 내림차순 확인
    assert data["tags"][0]["name"] == "family"  # 15
    assert data["tags"][1]["name"] == "work"  # 10
    assert data["tags"][2]["name"] == "travel"  # 5


def test_get_tags_sort_by_name(client, seeded_tags):
    """15.2 Right: GET /tags?sort_by=name → 이름 오름차순"""
    response = client.get("/api/ic/tags/?sort_by=name")

    assert response.status_code == 200
    data = response.json()

    # 이름 오름차순 확인
    assert data["tags"][0]["name"] == "family"
    assert data["tags"][1]["name"] == "travel"
    assert data["tags"][2]["name"] == "work"


def test_create_tag_success(client, test_db):
    """15.3 Right: POST /tags → 태그 생성"""
    response = client.post("/api/ic/tags/", json={"name": "vacation"})

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "created"
    assert "tag_id" in data

    # DB 확인
    tag = test_db.execute(text("SELECT name FROM tags WHERE name = 'vacation'")).fetchone()
    assert tag is not None


def test_create_tag_duplicate(client, seeded_tags):
    """15.4 Right: POST /tags (중복) → exists 응답"""
    response = client.post("/api/ic/tags/", json={"name": "work"})

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "exists"
    assert data["tag_id"] == 1


def test_bulk_tag_files(client, seeded_tags, test_db):
    """15.5 Right: POST /bulk-tag → 일괄 태그 부여"""
    response = client.post("/api/ic/tags/bulk-tag", json={
        "file_ids": [1, 2],
        "tag_names": ["work", "urgent"]
    })

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["files_tagged"] == 2

    # DB 확인 (file_tags 관계)
    relations = test_db.execute(text("SELECT COUNT(*) as count FROM file_tags")).fetchone()
    assert relations.count >= 2

    # urgent 태그 자동 생성 확인
    urgent_tag = test_db.execute(text("SELECT id FROM tags WHERE name = 'urgent'")).fetchone()
    assert urgent_tag is not None


def test_delete_tag_without_force(client, seeded_tags, test_db):
    """15.6 Error: DELETE /tags/{id} (사용 중) → 400"""
    # 파일-태그 관계 생성
    test_db.execute(text("""
        INSERT INTO file_tags (file_id, tag_id) VALUES (1, 1)
    """))
    test_db.commit()

    response = client.delete("/api/ic/tags/1?force=false")

    assert response.status_code == 400
    assert "사용 중" in response.json()["detail"]


def test_delete_tag_with_force(client, seeded_tags, test_db):
    """15.7 Right: DELETE /tags/{id}?force=true → 강제 삭제"""
    # 파일-태그 관계 생성
    test_db.execute(text("""
        INSERT INTO file_tags (file_id, tag_id) VALUES (1, 1)
    """))
    test_db.commit()

    response = client.delete("/api/ic/tags/1?force=true")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["relations_deleted"] >= 1

    # 태그 삭제 확인
    tag = test_db.execute(text("SELECT id FROM tags WHERE id = 1")).fetchone()
    assert tag is None


def test_delete_nonexistent_tag(client, test_db):
    """15.8 Error: DELETE /tags/9999 → 404"""
    response = client.delete("/api/ic/tags/9999")

    assert response.status_code == 404
    assert "찾을 수 없습니다" in response.json()["detail"]
