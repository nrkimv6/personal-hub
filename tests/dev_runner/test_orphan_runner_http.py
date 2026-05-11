"""HTTP contract tests for dev-runner orphan discovery and manual reattach."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.runner import router
from app.modules.dev_runner.schemas import OrphanRunnerCandidate, ReattachRunnerResponse

pytestmark = pytest.mark.http


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/dev-runner")
    return TestClient(app, raise_server_exceptions=False)


def _candidate(**overrides) -> OrphanRunnerCandidate:
    data = {
        "runner_id": "orphan-1",
        "plan_file": "docs/plan/orphan.md",
        "engine": "claude",
        "trigger": "user",
        "pid": 4321,
        "pid_kind": "parent",
        "log_file": "logs/plan-runner-stream-orphan-1.log",
        "log_mtime": datetime(2026, 5, 5, 23, 0, 0),
        "confidence": "high",
        "reattach_mode": "full",
        "can_reattach": True,
        "can_force_kill": True,
        "warnings": [],
    }
    data.update(overrides)
    return OrphanRunnerCandidate(**data)


def test_get_orphan_runners_http_returns_confidence_schema():
    candidate = _candidate()
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.discover_orphan_runners",
        new=AsyncMock(return_value=[candidate]),
    ):
        response = _client().get("/api/v1/dev-runner/runners/orphans")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["runner_id"] == "orphan-1"
    assert body[0]["confidence"] == "high"
    assert body[0]["can_reattach"] is True


def test_reattach_runner_http_success_returns_reconnect_contract():
    candidate = _candidate()
    payload = ReattachRunnerResponse(
        success=True,
        runner_id="orphan-1",
        message="reattached",
        candidate=candidate,
        reattach_mode="full",
    )
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.reattach_runner",
        new=AsyncMock(return_value=payload),
    ):
        response = _client().post(
            "/api/v1/dev-runner/runners/orphan-1/reattach",
            json={"expected_plan_file": "docs/plan/orphan.md"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["candidate"]["confidence"] == "high"
    assert body["reattach_mode"] == "full"


def test_reattach_runner_http_low_confidence_rejected():
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.reattach_runner",
        new=AsyncMock(side_effect=HTTPException(status_code=422, detail="candidate confidence is too low")),
    ):
        response = _client().post("/api/v1/dev-runner/runners/orphan-1/reattach", json={})

    assert response.status_code == 422
    assert "confidence" in response.json()["detail"]


def test_kill_orphan_runner_http_safety_rejection():
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.kill_orphan_runner",
        new=AsyncMock(side_effect=HTTPException(status_code=422, detail="PID evidence mismatch")),
    ):
        response = _client().post("/api/v1/dev-runner/runners/orphan-1/orphans/kill")

    assert response.status_code == 422
    assert "PID evidence" in response.json()["detail"]
