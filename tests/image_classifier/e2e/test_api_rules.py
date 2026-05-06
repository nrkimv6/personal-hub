"""분류 규칙 API 엔드포인트 테스트"""
import pytest
from sqlalchemy import text


@pytest.fixture
def seeded_rules(test_db):
    """분류 규칙 데이터 생성"""
    # 카테고리 생성 (FK 필요)
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES
        (1, 'Receipt', 'shopping/receipt'),
        (2, 'Travel', 'photos/travel'),
        (3, 'Unsorted', 'unsorted')
    """))

    # 규칙 3개 생성
    test_db.execute(text("""
        INSERT INTO classification_rules (id, rule_type, category_id, rule_content, priority, is_active, source) VALUES
        (1, 'filename', 1, 'receipt', 100, 1, 'user'),
        (2, 'folder_path', 2, 'travel', 90, 1, 'learned'),
        (3, 'keyword', 3, 'IMG', 50, 0, 'user')
    """))

    test_db.commit()


# ================================================
# Right: 기본 CRUD 동작
# ================================================

def test_get_rules(client, seeded_rules):
    """16.1 Right: GET /rules → priority DESC"""
    response = client.get("/api/ic/rules")

    assert response.status_code == 200
    rules = response.json()

    assert isinstance(rules, list)
    assert len(rules) == 3

    # priority 내림차순 확인
    assert rules[0]["priority"] == 100
    assert rules[1]["priority"] == 90
    assert rules[2]["priority"] == 50


def test_get_rules_structure(client, seeded_rules):
    """16.2 Right: 규칙 응답 구조 확인"""
    response = client.get("/api/ic/rules")

    assert response.status_code == 200
    rules = response.json()

    rule = rules[0]
    assert "id" in rule
    assert "rule_type" in rule
    assert "category_id" in rule
    assert "rule_content" in rule
    assert "priority" in rule
    assert "is_active" in rule

    assert rule["rule_type"] == "filename"
    assert rule["rule_content"] == "receipt"
    assert rule["category_id"] == 1
    assert rule["is_active"] is True


def test_create_rule(client, test_db):
    """16.3 Right: POST /rules → 규칙 생성"""
    # 카테고리 먼저 생성
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES (1, 'Work', 'work')
    """))
    test_db.commit()

    response = client.post("/api/ic/rules", json={
        "rule_type": "filename",
        "category_id": 1,
        "rule_content": "invoice",
        "priority": 80,
        "is_active": True
    })

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert "추가되었습니다" in data["message"]

    # DB 확인
    rule = test_db.execute(text("""
        SELECT rule_type, category_id, rule_content, priority
        FROM classification_rules
        WHERE rule_content = 'invoice'
    """)).fetchone()

    assert rule is not None
    assert rule.rule_type == "filename"
    assert rule.category_id == 1
    assert rule.priority == 80


def test_create_rule_default_values(client, test_db):
    """16.4 Boundary: POST /rules (기본값) → priority=0, is_active=true"""
    # 카테고리 먼저 생성
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES (1, 'Test', 'test')
    """))
    test_db.commit()

    response = client.post("/api/ic/rules", json={
        "category_id": 1,
        "rule_content": "test_pattern"
    })

    assert response.status_code == 200

    # DB 확인
    rule = test_db.execute(text("""
        SELECT rule_type, priority, is_active, source
        FROM classification_rules
        WHERE rule_content = 'test_pattern'
    """)).fetchone()

    assert rule.rule_type == "keyword"  # 기본값
    assert rule.priority == 0  # 기본값
    assert rule.is_active == 1  # 기본값 True
    assert rule.source == "user"  # 기본값


def test_delete_rule(client, seeded_rules, test_db):
    """16.5 Right: DELETE /rules/{id} → 규칙 삭제"""
    response = client.delete("/api/ic/rules/1")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert "삭제되었습니다" in data["message"]

    # DB 확인
    rule = test_db.execute(text("SELECT id FROM classification_rules WHERE id = 1")).fetchone()
    assert rule is None


def test_delete_nonexistent_rule(client, test_db):
    """16.6 Error: DELETE /rules/9999 → 404"""
    response = client.delete("/api/ic/rules/9999")

    assert response.status_code == 404
    assert "찾을 수 없습니다" in response.json()["detail"]


def test_get_empty_rules(client, test_db):
    """16.7 Boundary: GET /rules (빈 목록) → []"""
    response = client.get("/api/ic/rules")

    assert response.status_code == 200
    rules = response.json()

    assert isinstance(rules, list)
    assert len(rules) == 0


def test_rule_priority_ordering(client, test_db):
    """16.8 Right: 규칙 우선순위 정렬 확인"""
    # 카테고리 생성
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES
        (1, 'Cat1', 'cat1'), (2, 'Cat2', 'cat2'), (3, 'Cat3', 'cat3')
    """))

    # 규칙 추가 (우선순위 역순)
    test_db.execute(text("""
        INSERT INTO classification_rules (rule_type, category_id, rule_content, priority, is_active) VALUES
        ('keyword', 1, 'low', 10, 1),
        ('keyword', 2, 'high', 200, 1),
        ('keyword', 3, 'mid', 100, 1)
    """))
    test_db.commit()

    response = client.get("/api/ic/rules")

    assert response.status_code == 200
    rules = response.json()

    # priority 내림차순 확인
    assert rules[0]["rule_content"] == "high"
    assert rules[1]["rule_content"] == "mid"
    assert rules[2]["rule_content"] == "low"


def test_get_rules_includes_source_hit_count_and_category_name(client, seeded_rules, test_db):
    test_db.execute(text(
        "UPDATE classification_rules SET hit_count = 7 WHERE id = 1"
    ))
    test_db.commit()

    response = client.get("/api/ic/rules")

    assert response.status_code == 200
    rules = response.json()

    rule = next(item for item in rules if item["id"] == 1)
    assert rule["source"] == "user"
    assert rule["hit_count"] == 7
    assert rule["category_name"] == "shopping/receipt"


def test_get_rules_category_name_fallback_is_preserved(client, test_db):
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES (1, 'Travel', 'photos/travel')
    """))
    test_db.commit()
    test_db.execute(text("PRAGMA foreign_keys=OFF"))
    test_db.execute(text("""
        INSERT INTO classification_rules (id, rule_type, category_id, rule_content, priority, is_active, source, hit_count)
        VALUES (10, 'keyword', 99, 'fallback', 50, 1, 'learned', 5)
    """))
    test_db.commit()
    test_db.execute(text("PRAGMA foreign_keys=ON"))
    test_db.commit()

    response = client.get("/api/ic/rules")

    assert response.status_code == 200
    rules = response.json()

    rule = next(item for item in rules if item["id"] == 10)
    assert rule["source"] == "learned"
    assert rule["hit_count"] == 5
    assert rule["category_name"] == "99"
