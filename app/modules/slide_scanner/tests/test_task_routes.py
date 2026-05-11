from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.slide_scanner.routers import batch, export, mobile_review, slides, tasks

pytestmark = pytest.mark.http


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(slides.router, prefix="/api/v1/ss")
    app.include_router(batch.router, prefix="/api/v1/ss")
    app.include_router(export.router, prefix="/api/v1/ss")
    app.include_router(mobile_review.router, prefix="/api/v1/ss")
    app.include_router(tasks.router, prefix="/api/v1/ss")
    with TestClient(app) as c:
        yield c


def test_transform_task_start_does_not_transform_synchronously_R(client, monkeypatch):
    def fail_transform(*_args, **_kwargs):
        raise AssertionError("task start must not transform synchronously")

    monkeypatch.setattr(slides.rectifier_client, "transform", fail_transform)

    with patch("app.modules.slide_scanner.services.task_store.BackgroundTasks.add_task"):
        resp = client.post(
            "/api/v1/ss/slides/1/transform/tasks",
            json={"points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}]},
        )

    assert resp.status_code == 202
    assert resp.json()["task_id"]


def test_batch_transform_task_accepts_large_id_list_B(client):
    with patch("app.modules.slide_scanner.services.task_store.BackgroundTasks.add_task"):
        resp = client.post(
            "/api/v1/ss/slides/batch-transform/tasks",
            json={"ids": list(range(1, 1001))},
        )

    assert resp.status_code == 202
    assert resp.json()["task_id"]


def test_export_pdf_task_start_does_not_export_synchronously_R(client, monkeypatch):
    def fail_export(*_args, **_kwargs):
        raise AssertionError("task start must not export synchronously")

    monkeypatch.setattr(export.rectifier_client, "export_pdf", fail_export)

    with patch("app.modules.slide_scanner.services.task_store.BackgroundTasks.add_task"):
        resp = client.post("/api/v1/ss/export/pdf/tasks", json={"ids": [1], "filename": "deck.pdf"})

    assert resp.status_code == 202
    assert resp.json()["task_id"]


def test_remote_delete_task_start_does_not_delete_synchronously_R(client, monkeypatch):
    def fail_delete(*_args, **_kwargs):
        raise AssertionError("task start must not remote-delete synchronously")

    monkeypatch.setattr(mobile_review, "process_remote_delete_for_item", fail_delete)

    with patch("app.modules.slide_scanner.services.task_store.BackgroundTasks.add_task"):
        resp = client.post("/api/v1/ss/mobile-review/1/remote-delete/tasks")

    assert resp.status_code == 202
    assert resp.json()["task_id"]
