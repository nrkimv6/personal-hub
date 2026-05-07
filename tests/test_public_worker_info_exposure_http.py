"""Public HTTP surface must not expose worker/process diagnostics."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


PUBLIC_HEADERS = {"CF-Connecting-IP": "203.0.113.10"}
SENSITIVE_TOKENS = (
    "pid",
    "ppid",
    "process-watch",
    "watchdog",
    "listener",
    "runner_id",
    "log_path",
)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/worker/status",
        "/api/v1/worker/health",
        "/api/v1/worker/logs",
        "/api/v1/llm/worker/status",
        "/api/v1/system/process-tree",
        "/api/v1/system/process-history",
        "/api/v1/system/services/workers",
        "/api/v1/system/memory",
        "/api/v1/system/death-log",
        "/api/v1/system/boot-history",
    ],
)
def test_public_http_E_does_not_expose_worker_process_details(path):
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(path, headers=PUBLIC_HEADERS)

    assert response.status_code == 403
    body = json.dumps(response.json(), ensure_ascii=False).lower()
    for token in SENSITIVE_TOKENS:
        assert token not in body


def test_public_http_R_allows_readiness_without_worker_details():
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/system/liveness", headers=PUBLIC_HEADERS)

    assert response.status_code == 200
    body = json.dumps(response.json(), ensure_ascii=False).lower()
    for token in SENSITIVE_TOKENS:
        assert token not in body


def test_admin_localhost_R_keeps_worker_diagnostics_available():
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/worker/status")

    assert response.status_code in (200, 503)
