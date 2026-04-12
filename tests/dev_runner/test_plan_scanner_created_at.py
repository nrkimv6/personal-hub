"""
TC: plan-list created_at 필드 — API 응답 검증 (T5 HTTP 통합)

plan: 2026-04-06_fix-dev-runner-todos-scroll-and-plan-list-sort.md
- T5: GET /api/v1/dev-runner/plans 응답에 created_at 필드 존재 확인
"""
import pytest
import requests

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"


def test_plan_list_created_at_field():
    """
    GET /api/v1/dev-runner/plans 응답 JSON의 각 plan 항목에
    'created_at' 키가 존재해야 한다 (None 허용, 필드 자체 없으면 실패).
    """
    resp = requests.get(f"{BASE_URL}/api/v1/dev-runner/plans", timeout=10)
    assert resp.status_code == 200, f"plans API 응답 실패: {resp.status_code}"

    plans = resp.json()
    assert isinstance(plans, list), "응답이 list여야 함"
    assert len(plans) > 0, "plan 목록이 비어있음 — 서버 상태 확인 필요"

    for item in plans:
        assert "created_at" in item, (
            f"'created_at' 필드 누락: {item.get('filename', '?')} — "
            f"PlanFileResponse 스키마에 created_at 필드가 추가되지 않았거나 API가 재시작되지 않음"
        )
