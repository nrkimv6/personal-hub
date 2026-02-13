"""분류 규칙 API 엔드포인트 테스트 (단순 CRUD 검증용)"""
import pytest
from sqlalchemy import text


# ================================================
# Right: 기본 CRUD 동작
# ================================================

def test_get_empty_rules(client, test_db):
    """16.1 Right: GET /rules (빈 목록) → []"""
    response = client.get("/api/ic/rules")

    assert response.status_code == 200
    rules = response.json()

    assert isinstance(rules, list)
    assert len(rules) == 0


def test_delete_nonexistent_rule(client, test_db):
    """16.2 Error: DELETE /rules/9999 → 404"""
    response = client.delete("/api/ic/rules/9999")

    assert response.status_code == 404
    assert "찾을 수 없습니다" in response.json()["detail"]


# NOTE: rules.py와 실제 DB 스키마 불일치로 나머지 테스트는 TODO
# rules.py는 pattern/category_path/enabled를 사용하지만
# DB는 rule_type/category_id/rule_content/is_active를 사용함
# 실제 규칙 생성/조회 기능은 routes.py 수정 후 테스트 가능
