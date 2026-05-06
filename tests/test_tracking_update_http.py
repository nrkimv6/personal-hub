import os

import httpx
import pytest


pytestmark = pytest.mark.http_live

ADMIN_API = os.environ.get("MONITOR_ADMIN_API_BASE", "http://localhost:8001")


def _client() -> httpx.Client:
    token = os.environ.get("MONITOR_ADMIN_TOKEN")
    if not token:
        pytest.skip("MONITOR_ADMIN_TOKEN is not set")
    return httpx.Client(
        base_url=ADMIN_API,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=10.0,
    )


def _delete_item(client: httpx.Client, item_id: int) -> None:
    client.delete(f"/api/v1/tracking/items/{item_id}")


def test_tracking_patch_accepts_start_at_update_and_clear_deadline():
    with _client() as client:
        response = client.post(
            "/api/v1/tracking/items",
            json={"title": "T5 update", "due_at": "2099-12-31T23:59:00"},
        )
        if response.status_code in (401, 403):
            pytest.skip(f"Admin auth rejected request: {response.status_code}")
        assert response.status_code == 201, response.text
        item_id = response.json()["id"]

        try:
            patch_response = client.patch(
                f"/api/v1/tracking/items/{item_id}",
                json={"start_at": "2099-01-01T00:00:00", "due_at": None},
            )
            assert patch_response.status_code == 200, patch_response.text
            data = patch_response.json()
            assert data["start_at"] is not None
            assert data["due_at"] is None
        finally:
            _delete_item(client, item_id)


def test_tracking_patch_rejects_both_dates_null():
    with _client() as client:
        response = client.post(
            "/api/v1/tracking/items",
            json={"title": "T5 update reject", "due_at": "2099-12-31T23:59:00"},
        )
        if response.status_code in (401, 403):
            pytest.skip(f"Admin auth rejected request: {response.status_code}")
        assert response.status_code == 201, response.text
        item_id = response.json()["id"]

        try:
            patch_response = client.patch(
                f"/api/v1/tracking/items/{item_id}",
                json={"start_at": None, "due_at": None},
            )
            assert patch_response.status_code == 400, patch_response.text
            assert (
                patch_response.json()["detail"]
                == "start_at 또는 due_at 중 하나 이상이 필요합니다."
            )
        finally:
            _delete_item(client, item_id)
