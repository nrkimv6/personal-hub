from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.image_classifier.routers import classify

pytestmark = pytest.mark.http


class _DummyDb:
    def close(self) -> None:
        pass


@pytest.fixture
def client():
    classify.classification_status = {
        "running": False,
        "total": 0,
        "processed": 0,
        "failed": 0,
        "current_file": None,
        "model": None,
    }
    app = FastAPI()

    def override_get_db():
        yield _DummyDb()

    app.dependency_overrides[classify.get_db] = override_get_db
    app.include_router(classify.router, prefix="/api/ic")
    with TestClient(app) as c:
        yield c
    classify.classification_status["running"] = False


def test_smart_start_returns_without_auto_map_sync_R(client, monkeypatch):
    def fail_sync_auto_map(*_args, **_kwargs):
        raise AssertionError("smart-start route must not run auto_map_folders synchronously")

    class FailingFolderClassifier:
        def __init__(self, *_args, **_kwargs):
            pass

        auto_map_folders = fail_sync_auto_map

    monkeypatch.setattr("app.modules.image_classifier.workers.folder_classifier.FolderClassifier", FailingFolderClassifier)

    with patch("app.modules.image_classifier.routers.classify.BackgroundTasks.add_task"):
        resp = client.post("/api/ic/classify/smart-start", json={"model": "claude_cli"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["total"] == 0
    assert classify.classification_status["phase"] == "smart_preparing"
