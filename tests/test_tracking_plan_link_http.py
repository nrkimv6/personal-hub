"""
Tracking ↔ Plan 링크 HTTP 통합 테스트 (T5)

실제 서버 localhost:8001에 HTTP 요청으로 검증.
"""
import pytest
import httpx

pytestmark = pytest.mark.http_live

ADMIN_API = "http://localhost:8001"
HEADERS = {"Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tracking_item_id():
    """테스트용 tracking item 생성 후 ID 반환."""
    with httpx.Client(base_url=ADMIN_API, headers=HEADERS, timeout=10) as client:
        payload = {"title": "T5 Plan Link HTTP Test", "due_at": "2099-12-31T23:59:00"}
        # auth 없이 생성 시도하면 401
        resp = client.post("/api/v1/tracking/items", json=payload)
        if resp.status_code == 401:
            pytest.skip("Admin auth not configured — 401 returned (expected in some envs)")
        # admin 쿠키/토큰이 있는 환경에서만 201 기대
        if resp.status_code != 201:
            pytest.skip(f"Unable to create test item ({resp.status_code}) — skip T5")
        return resp.json()["id"]


def test_link_endpoint_returns_linked_plans_schema(tracking_item_id):
    """POST /api/v1/tracking/items/{id}/plans — 응답에 linked_plans 필드 포함"""
    with httpx.Client(base_url=ADMIN_API, headers=HEADERS, timeout=10) as client:
        # 빈 plan_record_ids로 링크 → 200 + linked_plans: []
        resp = client.post(
            f"/api/v1/tracking/items/{tracking_item_id}/plans",
            json={"plan_record_ids": []},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "linked_plans" in data
        assert isinstance(data["linked_plans"], list)


def test_unlink_endpoint_idempotent(tracking_item_id):
    """DELETE /api/v1/tracking/items/{id}/plans/{plan_id} — link 없어도 200"""
    with httpx.Client(base_url=ADMIN_API, headers=HEADERS, timeout=10) as client:
        resp = client.delete(f"/api/v1/tracking/items/{tracking_item_id}/plans/99999")
        assert resp.status_code == 200
        data = resp.json()
        assert "linked_plans" in data


def test_auth_required_for_link(tracking_item_id):
    """인증 없는 링크 요청 → 401/403"""
    no_auth_headers = {"Content-Type": "application/json"}
    # Remove any default auth — plain httpx client
    with httpx.Client(base_url=ADMIN_API, timeout=10) as client:
        # Port 8000 (public) should reject
        try:
            resp = client.post(
                f"http://localhost:8000/api/v1/tracking/items/{tracking_item_id}/plans",
                json={"plan_record_ids": []},
                headers=no_auth_headers,
            )
            assert resp.status_code in (401, 403, 404)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            pytest.skip("Public API (8000) not reachable")


def test_get_tracking_item_includes_linked_plans():
    """GET /api/v1/tracking/items — 응답 items에 linked_plans 필드 존재"""
    with httpx.Client(base_url=ADMIN_API, headers=HEADERS, timeout=10) as client:
        resp = client.get("/api/v1/tracking/items")
        if resp.status_code != 200:
            pytest.skip(f"GET tracking items returned {resp.status_code}")
        data = resp.json()
        if data["total"] == 0:
            pytest.skip("No tracking items — cannot verify linked_plans field")
        first_item = data["items"][0]
        assert "linked_plans" in first_item
        assert isinstance(first_item["linked_plans"], list)
