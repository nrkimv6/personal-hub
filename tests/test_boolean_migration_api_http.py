"""
T5: HTTP 통합 테스트 — boolean 마이그레이션 후 API 엔드포인트 정상 동작 확인
monitor_schedules.is_enabled = true 쿼리 포함 경로가 500 에러 없이 200 반환하는지 검증.

관련 plan: docs/plan/2026-04-11_fix-boolean-column-type-pg-migration.md
실행: main 머지 후 /merge-test 또는 pytest tests/test_boolean_migration_api_http.py
"""
import pytest
import requests

BASE_URL = "http://localhost:8001"


@pytest.fixture(scope="module")
def client():
    """HTTP 클라이언트 — 실행 중인 서버에 직접 요청"""
    return requests.Session()


def test_dashboard_unified_200_after_migration(client):
    """T5: GET /api/v1/dashboard/unified → 200 OK
    monitor_schedules.is_enabled = true 쿼리 포함 — 마이그레이션 전 integer = boolean 에러로 500 발생했을 경로
    """
    resp = client.get(f"{BASE_URL}/api/v1/dashboard/unified", timeout=10)
    assert resp.status_code == 200, (
        f"dashboard/unified 500 에러: {resp.status_code} {resp.text[:200]}"
    )


def test_system_status_200_after_migration(client):
    """T5: GET /api/v1/system/status → 200 OK
    monitor_schedules.is_enabled 카운트 쿼리 포함
    """
    resp = client.get(f"{BASE_URL}/api/v1/system/status", timeout=10)
    assert resp.status_code == 200, (
        f"system/status 500 에러: {resp.status_code} {resp.text[:200]}"
    )


def test_worker_status_200_after_migration(client):
    """T5: GET /api/v1/worker/status → 200 OK
    is_enabled = true 쿼리 포함
    """
    resp = client.get(f"{BASE_URL}/api/v1/worker/status", timeout=10)
    assert resp.status_code == 200, (
        f"worker/status 500 에러: {resp.status_code} {resp.text[:200]}"
    )


def test_worker_status_200_schema_after_fix(client):
    """T5: GET /api/v1/worker/status → 200 + 스키마 검증
    수정 후 스키마: started_at 존재, start_time/browser_available 제거됨.
    """
    resp = client.get(f"{BASE_URL}/api/v1/worker/status", timeout=10)
    assert resp.status_code == 200, (
        f"worker/status 500 에러: {resp.status_code} {resp.text[:200]}"
    )
    data = resp.json()
    assert "started_at" in data, f"started_at 필드가 응답에 없음: {list(data.keys())}"
    assert "start_time" not in data, f"start_time은 제거된 필드인데 응답에 존재: {list(data.keys())}"
    assert "browser_available" not in data, (
        f"browser_available은 제거된 필드인데 응답에 존재: {list(data.keys())}"
    )
