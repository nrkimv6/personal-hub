from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.image_classifier.routers import duplicates

pytestmark = pytest.mark.http


@pytest.fixture
def client():
    duplicates._duplicate_tasks.clear()
    app = FastAPI()
    app.include_router(duplicates.router, prefix="/api/ic")
    with TestClient(app) as c:
        yield c
    duplicates._duplicate_tasks.clear()


def test_folder_analysis_task_returns_accepted_without_sync_call_R(client, monkeypatch):
    def fail_sync_call(*_args, **_kwargs):
        raise AssertionError("task start must not run folder analysis synchronously")

    monkeypatch.setattr(duplicates, "get_folder_analysis", fail_sync_call)
    with patch("app.modules.image_classifier.routers.duplicates.BackgroundTasks.add_task"):
        resp = client.post("/api/ic/duplicates/folder-analysis/tasks")

    assert resp.status_code == 202
    body = resp.json()
    assert body["task_id"]
    assert body["status"] == "queued"


def test_bulk_resolve_task_accepts_large_resolution_list_B(client):
    payload = {
        "resolutions": [
            {"group_id": group_id, "keep_file_id": group_id * 10}
            for group_id in range(1, 1001)
        ]
    }

    with patch("app.modules.image_classifier.routers.duplicates.BackgroundTasks.add_task"):
        resp = client.post("/api/ic/duplicates/bulk-resolve/tasks", json=payload)

    assert resp.status_code == 202
    assert resp.json()["task_id"]


def test_duplicate_task_status_reports_failed_task_E(client):
    with patch("app.modules.image_classifier.routers.duplicates.BackgroundTasks.add_task"):
        create_resp = client.post(
            "/api/ic/duplicates/auto-resolve/tasks",
            json={"filter": "all", "strategy": "quality_best", "group_ids": []},
        )
    task_id = create_resp.json()["task_id"]
    duplicates._complete_duplicate_task(task_id, "failed", error="Redis unavailable; async fallback refused")

    status_resp = client.get(f"/api/ic/duplicates/tasks/{task_id}")

    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] == "failed"
    assert "Redis unavailable" in body["error_message"]
