"""분류 규칙 API 엔드포인트 테스트"""
import pytest
from sqlalchemy import text


@pytest.fixture
def seeded_rules(test_db):
    """분류 규칙 데이터 생성"""
    # 규칙 3개 생성
    test_db.execute(text("""
        INSERT INTO classification_rules (id, pattern, category_path, priority, enabled) VALUES
        (1, '*receipt*', 'shopping/receipt', 100, 1),
        (2, '*travel*', 'photos/travel', 90, 1),
        (3, 'IMG_*', 'unsorted', 50, 0)
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
    assert "pattern" in rule
    assert "category_path" in rule
    assert "priority" in rule
    assert "enabled" in rule

    assert rule["pattern"] == "*receipt*"
    assert rule["category_path"] == "shopping/receipt"
    assert rule["enabled"] is True


def test_create_rule(client, test_db):
    """16.3 Right: POST /rules → 규칙 생성"""
    response = client.post("/api/ic/rules", json={
        "pattern": "*invoice*",
        "category_path": "work/invoice",
        "priority": 80,
        "enabled": True
    })

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert "추가되었습니다" in data["message"]

    # DB 확인
    rule = test_db.execute(text("""
        SELECT pattern, category_path, priority
        FROM classification_rules
        WHERE pattern = '*invoice*'
    """)).fetchone()

    assert rule is not None
    assert rule.category_path == "work/invoice"
    assert rule.priority == 80


def test_create_rule_default_values(client, test_db):
    """16.4 Boundary: POST /rules (기본값) → priority=100, enabled=true"""
    response = client.post("/api/ic/rules", json={
        "pattern": "test_*",
        "category_path": "test"
    })

    assert response.status_code == 200

    # DB 확인
    rule = test_db.execute(text("""
        SELECT priority, enabled
        FROM classification_rules
        WHERE pattern = 'test_*'
    """)).fetchone()

    assert rule.priority == 100  # 기본값
    assert rule.enabled == 1  # 기본값 True


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
    # 규칙 추가 (우선순위 역순)
    test_db.execute(text("""
        INSERT INTO classification_rules (pattern, category_path, priority, enabled) VALUES
        ('low', 'cat1', 10, 1),
        ('high', 'cat2', 200, 1),
        ('mid', 'cat3', 100, 1)
    """))
    test_db.commit()

    response = client.get("/api/ic/rules")

    assert response.status_code == 200
    rules = response.json()

    # priority 내림차순 확인
    assert rules[0]["pattern"] == "high"
    assert rules[1]["pattern"] == "mid"
    assert rules[2]["pattern"] == "low"
