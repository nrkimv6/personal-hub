"""T5 HTTP: GET /api/v1/file-search/status HTTP 통합 테스트.

TestClient + dependency_override로 DB 격리. EverythingService/RipgrepService는
실제 호출되며, 환경에 따라 결과가 달라지므로 스키마 매칭 + 응답 형식만 검증.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.modules.file_search.routes import router as file_search_router

pytestmark = pytest.mark.http

BASE = "/api/v1/file-search"


@pytest.fixture
def app_with_db_override():
    app = FastAPI()
    app.include_router(file_search_router)

    def _fake_get_db():
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        yield db

    app.dependency_overrides[get_db] = _fake_get_db
    return app


@pytest.fixture
def client(app_with_db_override):
    return TestClient(app_with_db_override)


def test_get_status_http_returns_200_and_schema(client):
    """GET /status → 200 + StatusResponse 스키마(everything_ok/ripgrep_ok bool)."""
    with patch(
        "app.modules.file_search.routes.EverythingService"
    ) as mock_everything, patch(
        "app.modules.file_search.routes.RipgrepService"
    ) as mock_ripgrep:
        mock_everything.return_value.is_available = AsyncMock(return_value=(True, ""))
        mock_ripgrep.return_value.is_available = MagicMock(return_value=(False, None))

        resp = client.get(f"{BASE}/status")

    assert resp.status_code == 200
    body = resp.json()
    assert "everything_ok" in body
    assert "everything_message" in body
    assert "ripgrep_ok" in body
    assert "ripgrep_path" in body
    assert isinstance(body["everything_ok"], bool)
    assert isinstance(body["ripgrep_ok"], bool)


def test_get_status_http_both_ok(client, tmp_path):
    """정상 환경(둘 다 ok) HTTP 응답 검증."""
    rg = tmp_path / "rg.exe"
    rg.write_bytes(b"")

    with patch(
        "app.modules.file_search.routes.EverythingService"
    ) as mock_everything, patch(
        "app.modules.file_search.routes.RipgrepService"
    ) as mock_ripgrep:
        mock_everything.return_value.is_available = AsyncMock(return_value=(True, ""))
        mock_ripgrep.return_value.is_available = MagicMock(return_value=(True, str(rg)))

        resp = client.get(f"{BASE}/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["everything_ok"] is True
    assert body["ripgrep_ok"] is True
    assert body["ripgrep_path"] == str(rg)


def test_get_status_http_everything_failure_message(client):
    """Everything 연결 실패 시 메시지에 워커 미실행 표현 없음."""
    with patch(
        "app.modules.file_search.routes.EverythingService"
    ) as mock_everything, patch(
        "app.modules.file_search.routes.RipgrepService"
    ) as mock_ripgrep:
        mock_everything.return_value.is_available = AsyncMock(
            return_value=(False, "연결 실패 (포트: 7780)")
        )
        mock_ripgrep.return_value.is_available = MagicMock(return_value=(False, None))

        resp = client.get(f"{BASE}/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["everything_ok"] is False
    assert "워커 미실행" not in body["everything_message"]
    assert "연결 실패" in body["everything_message"]
