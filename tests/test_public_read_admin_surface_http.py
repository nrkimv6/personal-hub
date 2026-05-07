"""Public read API exposure contract."""

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.main import app


PUBLIC_HEADERS = {"CF-Connecting-IP": "203.0.113.10"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def public_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.middleware.settings.APP_MODE", "public")


@pytest.fixture
def admin_headers() -> dict[str, str]:
    token = create_access_token(email="admin@example.test", is_admin=True)
    return {"Authorization": f"Bearer {token}", **PUBLIC_HEADERS}


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/dev-runner/status",
        "/api/v1/dev-runner/runners",
        "/api/v1/dev-runner/merge-history",
        "/api/v1/plans/records",
        "/api/v1/plans/events",
        "/api/v1/git-repos/status",
        "/api/v1/file-search/status",
        "/api/v1/test-runs",
        "/api/v1/claude-sessions",
        "/api/v1/system/services/workers",
        "/api/v1/system/process-tree",
        "/api/v1/system/death-log",
        "/api/v1/system/boot-history",
        "/api/v1/worker/status",
        "/api/v1/llm/worker/status",
        "/api/v1/ss/scan/status",
        "/api/ic/files",
        "/api/fc/files",
    ],
)
def test_public_external_admin_only_read_returns_403(client: TestClient, path: str) -> None:
    response = client.get(path, headers=PUBLIC_HEADERS)

    assert response.status_code == 403
    data = response.json()
    assert data["blocked_action"] == f"GET {path}"
    assert data["mode"] == "public"
    assert "관리자" in data["hint"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/system/liveness",
        "/api/v1/system/mode",
        "/api/v1/health",
        "/api/v1/auth/me",
        "/api/v1/events",
        "/api/v1/popups",
        "/api/v1/monitoring/events/coupang-public-history",
        "/api/v1/expo/maps/example",
        "/api/v1/does-not-exist-public-contract",
    ],
)
def test_public_safe_or_unknown_read_is_not_blocked_by_middleware(client: TestClient, path: str) -> None:
    response = client.get(path, headers=PUBLIC_HEADERS)

    assert response.status_code != 403


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/dev-runner/status",
        "/api/v1/plans/records",
        "/api/v1/git-repos/status",
        "/api/v1/file-search/status",
        "/api/v1/system/services/workers",
    ],
)
def test_admin_token_can_reach_admin_only_read_middleware(client: TestClient, admin_headers: dict[str, str], path: str) -> None:
    response = client.get(path, headers=admin_headers)

    assert response.status_code != 403


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/dev-runner/status",
        "/api/v1/plans/records",
        "/api/v1/git-repos/status",
        "/api/v1/file-search/status",
        "/api/v1/system/services/workers",
    ],
)
def test_localhost_can_reach_admin_only_read_middleware(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code != 403


def test_path_segment_boundary_does_not_block_similar_public_path(client: TestClient) -> None:
    response = client.get("/api/v1/systemic/status", headers=PUBLIC_HEADERS)

    assert response.status_code != 403
