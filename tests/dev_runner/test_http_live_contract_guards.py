"""HTTP/live failure-contract guards that do not require a live server."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.logs import router as logs_router
from app.modules.dev_runner.schemas import RunHistoryResponse

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"


def _logs_client() -> TestClient:
    app = FastAPI()
    app.include_router(logs_router, prefix=BASE_URL)
    return TestClient(app, raise_server_exceptions=True)


def test_root_health_contract_is_readiness_200():
    """R: live health smoke uses the admin root readiness contract, not SPA fallback."""
    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_log_stream_route_forwards_since_line_without_history_lookup():
    """R: since_line is passed to the SSE service directly, avoiding history scans/timeouts."""

    async def _fake_stream_log_file(runner_id: str, since_line: int = 0):
        assert runner_id == "guard-since-line"
        assert since_line == 95
        yield "event: connected\ndata: ok\n\n"
        yield "data: [12:00:00] [INFO] line 95\n\n"

    with patch(
        "app.modules.dev_runner.routes.logs.log_service.stream_log_file",
        new=_fake_stream_log_file,
    ):
        response = _logs_client().get(
            f"{BASE_URL}/logs/stream",
            params={"runner_id": "guard-since-line", "since_line": 95},
            headers={"Accept": "text/event-stream"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert "line 95" in response.text


def test_logs_history_route_forwards_visible_only_true_to_service():
    """R: visible_only=true stays a service filter instead of a route-level slow path."""
    captured = {}

    def _fake_get_run_history(*, limit: int, offset: int, visible_only: bool):
        captured.update(limit=limit, offset=offset, visible_only=visible_only)
        return RunHistoryResponse(runs=[], total=0)

    with patch(
        "app.modules.dev_runner.routes.logs.log_service.get_run_history",
        side_effect=_fake_get_run_history,
    ):
        response = _logs_client().get(
            f"{BASE_URL}/logs/history",
            params={"visible_only": "true", "limit": 7, "offset": 2},
        )

    assert response.status_code == 200
    assert response.json() == {"runs": [], "total": 0}
    assert captured == {"limit": 7, "offset": 2, "visible_only": True}
