"""
T1: admin-only mutation endpoint 권한 테스트.
Phase 3B: archive-candidates/queue, archive-candidates/preview 는 admin 전용.
public app(:8000) 에서 호출 시 404/405 응답 확인.
"""
import pytest


def _get_public_app():
    """public app 인스턴스 반환. import 실패 시 skip."""
    try:
        from app.main import app as public_app
        return public_app
    except Exception:
        pytest.skip("public app import 실패 — skip")


def _get_admin_app():
    """admin app 인스턴스 반환. import 실패 시 skip."""
    try:
        from app.main_admin import app as admin_app
        return admin_app
    except Exception:
        pytest.skip("admin app import 실패 — skip")


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/api/v1/plans/records/archive-candidates/queue", {"candidate_keys": [], "record_ids": []}),
    ("POST", "/api/v1/plans/records/archive-candidates/preview", None),
])
def test_public_app_does_not_expose_mutation_endpoints(method, path, body):
    """public app 에서 mutation endpoint 호출 시 404/405 반환."""
    from fastapi.testclient import TestClient
    public_app = _get_public_app()
    client = TestClient(public_app, raise_server_exceptions=False)
    if method == "POST":
        resp = client.post(path, json=body)
    else:
        resp = client.request(method, path)
    assert resp.status_code in (404, 405), (
        f"public app 의 {path} 가 {resp.status_code} 을 반환함 — 404/405 기대"
    )


def test_admin_app_exposes_queue_endpoint():
    """admin app 에서 queue endpoint 가 접근 가능한지 확인 (404 가 아님)."""
    from fastapi.testclient import TestClient
    admin_app = _get_admin_app()
    client = TestClient(admin_app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/plans/records/archive-candidates/queue",
        json={"candidate_keys": [], "record_ids": []},
    )
    # DB 없어 500이 나도 괜찮음 — 중요한 건 404 가 아니어야 함
    assert resp.status_code != 404, f"admin app 의 queue endpoint 가 404 반환"
