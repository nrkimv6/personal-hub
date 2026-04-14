"""
라우트 순서 정합성 테스트 - 정적 경로가 파라미터 경로에 의해 가려지지 않는지 검증
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_check_duplicate_url_returns_200_not_422():
    """GET /api/v1/events/check-duplicate-url 이 /{event_id} 에 매칭되지 않아야 함"""
    resp = client.get("/api/v1/events/check-duplicate-url?url=http://non-existent-test.com")
    assert resp.status_code != 422, f"Shadowing detected: {resp.json()}"
    assert resp.status_code in [200, 401]

def test_presets_all_returns_200_not_422():
    """GET /api/v1/service-accounts/presets/all 이 /{account_id} 에 매칭되지 않아야 함"""
    resp = client.get("/api/v1/service-accounts/presets/all")
    assert resp.status_code != 422, f"Shadowing detected: {resp.json()}"
    assert resp.status_code in [200, 401, 403]

def test_import_from_instagram_not_shadowed():
    """POST /api/v1/events/import-from-instagram 이 /{event_id} 에 shadowing 되지 않아야 함"""
    # shadowing 되면 /{event_id} (GET) 에 매칭 시도 후 POST 이므로 405 발생 가능
    # shadowing 안 되면 실제 endpoint 에 매칭되고, body 가 없으므로 Pydantic validation error (422) 발생
    # 단, validation error 의 loc 은 ['body', ...] 이고 shadowing error 의 loc 은 ['path', 'event_id'] 임
    resp = client.post("/api/v1/events/import-from-instagram")
    if resp.status_code == 422:
        errors = resp.json().get("detail", [])
        for err in errors:
            # shadowing 시에는 path parameter 인 event_id 에 대한 에러가 남
            assert err.get("loc") != ["path", "event_id"], f"Shadowing detected in path: {err}"
    
    assert resp.status_code != 405, "Shadowed and returned 405 Method Not Allowed"

