from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.file_classifier.routers import obsidian

pytestmark = pytest.mark.http


def test_obsidian_classify_sample_returns_task_without_subprocess_R(monkeypatch):
    def fail_subprocess(*_args, **_kwargs):
        raise AssertionError("classify sample route must not run claude synchronously")

    monkeypatch.setattr("subprocess.run", fail_subprocess)

    app = FastAPI()
    app.include_router(obsidian.router, prefix="/api/fc")
    with patch("app.modules.file_classifier.routers.obsidian.BackgroundTasks.add_task") as add_task:
        with TestClient(app) as client:
            resp = client.post("/api/fc/obsidian/classify/sample?sample_size=2")

    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"]
    assert body["status"] == "pending"
    assert body["phase"] == "queued"
    add_task.assert_called_once()
