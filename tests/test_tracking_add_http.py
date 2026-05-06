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


def test_tracking_create_accepts_start_at_only_and_due_at_only():
    with _client() as client:
        response = client.post(
            "/api/v1/tracking/items",
            json={"title": "T5 start_at only", "start_at": "2099-01-01T00:00:00"},
        )
        if response.status_code in (401, 403):
            pytest.skip(f"Admin auth rejected request: {response.status_code}")
        assert response.status_code == 201, response.text
        start_item_id = response.json()["id"]

        response = client.post(
            "/api/v1/tracking/items",
            json={"title": "T5 due_at only", "due_at": "2099-12-31T23:59:00"},
        )
        assert response.status_code == 201, response.text
        due_item_id = response.json()["id"]

        try:
            start_item = client.get(f"/api/v1/tracking/items/{start_item_id}").json()
            due_item = client.get(f"/api/v1/tracking/items/{due_item_id}").json()
            assert start_item["start_at"] is not None
            assert start_item["due_at"] is None
            assert due_item["start_at"] is None
            assert due_item["due_at"] is not None
        finally:
            _delete_item(client, start_item_id)
            _delete_item(client, due_item_id)


def test_tracking_create_link_plan_by_path_flow():
    plan_path = ".worktrees/plans/docs/plan/2026-04-29_feat-tracking-item-cli-wrapper.md"
    with _client() as client:
        record_response = client.get("/api/v1/plans/records/by-path", params={"file_path": plan_path})
        assert record_response.status_code == 200, record_response.text
        plan_record_id = record_response.json()["id"]

        response = client.post(
            "/api/v1/tracking/items",
            json={"title": "T5 link plan", "due_at": "2099-12-31T23:59:00"},
        )
        if response.status_code in (401, 403):
            pytest.skip(f"Admin auth rejected request: {response.status_code}")
        assert response.status_code == 201, response.text
        item_id = response.json()["id"]

        try:
            link_response = client.post(
                f"/api/v1/tracking/items/{item_id}/plans",
                json={"plan_record_ids": [plan_record_id]},
            )
            assert link_response.status_code == 200, link_response.text
            linked = link_response.json()["linked_plans"]
            assert any(plan["plan_record_id"] == plan_record_id for plan in linked)
        finally:
            _delete_item(client, item_id)
