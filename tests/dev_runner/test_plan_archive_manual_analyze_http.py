"""Plan Archive manual analyze HTTP contract tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.http


@pytest.fixture
def client():
    from app.database import get_db
    from app.main import app

    def override_get_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _response(**overrides):
    data = {
        "success": True,
        "mode": "preview",
        "result": {"category": "infra"},
        "raw_response": '{"category":"infra"}',
        "provider": "codex",
        "model": "gpt-5.5",
        "record_id": 1,
        "filename_hash": "hash",
        "file_path": "/archive/file.md",
        "elapsed_ms": 10,
        "prompt_preview": None,
        "prompt_policy_id": "plan_archive.codex.default",
        "prompt_policy_version": "2026-05-06.1",
        "warnings": [],
        "saved": False,
        "record_after": None,
        "save_error": None,
    }
    data.update(overrides)
    return data


def test_post_analyze_response_includes_policy_metadata(client):
    with patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.PlanArchiveManualAnalyzeService.analyze",
        return_value=_response(),
    ) as mock_analyze:
        resp = client.post(
            "/api/v1/plans/records/1/analyze",
            json={"mode": "preview", "provider": "codex", "model": "gpt-5.5"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "codex"
    assert data["model"] == "gpt-5.5"
    assert data["prompt_policy_id"] == "plan_archive.codex.default"
    assert data["prompt_policy_version"] == "2026-05-06.1"
    assert mock_analyze.call_args.kwargs["provider"] == "codex"
    assert mock_analyze.call_args.kwargs["model"] == "gpt-5.5"


def test_post_analyze_dry_run_rejects_apply_mode(client):
    resp = client.post(
        "/api/v1/plans/records/1/analyze-dry-run",
        json={"mode": "apply"},
    )

    assert resp.status_code == 400
    assert "preview" in resp.json()["detail"]


def test_post_analyze_unknown_provider_returns_clear_error(client):
    with patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.PlanArchiveManualAnalyzeService.analyze",
        return_value=_response(
            success=False,
            provider="unknown",
            model="unknown-model",
            error="UNKNOWN_PROVIDER: unknown",
        ),
    ):
        resp = client.post(
            "/api/v1/plans/records/1/analyze",
            json={"mode": "preview", "provider": "unknown", "model": "unknown-model"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "UNKNOWN_PROVIDER" in data["error"]
