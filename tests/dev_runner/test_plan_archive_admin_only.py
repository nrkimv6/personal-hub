"""
T1: admin-only mutation endpoint 권한 테스트.
Plan Archive mutation endpoints must stay out of the public app.
"""
import os
import subprocess
import sys
from pathlib import Path

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
    ("POST", "/api/v1/plans/records/archive-category-repair", {"apply": False, "limit": 1}),
    ("POST", "/api/v1/plans/records/archive-schedule/pause", None),
    ("POST", "/api/v1/plans/records/archive-schedule/resume", None),
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


@pytest.mark.parametrize("path", [
    "/api/v1/plans/records/archive-candidates/queue",
    "/api/v1/plans/records/archive-candidates/preview",
    "/api/v1/plans/records/archive-category-repair",
    "/api/v1/plans/records/archive-schedule/pause",
    "/api/v1/plans/records/archive-schedule/resume",
])
def test_admin_app_registers_mutation_endpoints(path):
    """admin app keeps mutation routes registered after route module split."""
    admin_app = _get_admin_app()
    assert any(
        route.path == path and "POST" in getattr(route, "methods", set())
        for route in admin_app.routes
    ), f"admin app did not register {path}"


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


def _route_presence_for_main_app(app_mode: str, path: str) -> bool:
    code = (
        "from app.main import app\n"
        f"print(any(route.path == {path!r} and 'POST' in getattr(route, 'methods', set()) for route in app.routes))\n"
    )
    env = {**os.environ, "APP_MODE": app_mode, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1] == "True"


def test_main_app_admin_mode_exposes_schedule_mutations_but_public_does_not():
    """운영 서비스가 쓰는 app.main도 APP_MODE=admin에서 admin-only schedule mutation을 등록한다."""
    path = "/api/v1/plans/records/archive-schedule/resume"
    assert _route_presence_for_main_app("admin", path) is True
    assert _route_presence_for_main_app("public", path) is False
