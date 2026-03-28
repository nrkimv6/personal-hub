"""
health.py app.state 참조 패턴 검증 테스트

모듈 전역 변수(_health_monitor) 제거 후 request.app.state.health_monitor 참조로
올바르게 동작하는지 확인한다.
"""
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "1")


@pytest.fixture
def app_with_router():
    """health router를 포함한 FastAPI app 생성"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.health import router

    app = FastAPI()
    app.state.health_monitor = None
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture
def client(app_with_router):
    from fastapi.testclient import TestClient
    return TestClient(app_with_router)


def test_health_status_returns_empty_when_no_monitor(client, app_with_router):
    """R(Right): health_monitor 미설정 시 enabled=True + 빈 데이터 반환 (getattr fallback 검증)"""
    app_with_router.state.health_monitor = None

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.HEALTH_MONITOR_ENABLED = True

        response = client.get("/api/v1/health/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["services"] == {}
    assert data["recent_alerts"] == []


def test_health_status_with_monitor_on_app_state(client, app_with_router):
    """R(Right): app.state.health_monitor 설정 시 mock 데이터 반환"""
    mock_monitor = MagicMock()
    mock_monitor.get_all_services_status.return_value = {
        "api": {"status": "healthy", "last_check": "2026-03-29T10:00:00", "failure_count": 0}
    }
    mock_monitor.get_recent_alerts.return_value = []
    app_with_router.state.health_monitor = mock_monitor

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.HEALTH_MONITOR_ENABLED = True

        response = client.get("/api/v1/health/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert "api" in data["services"]

    app_with_router.state.health_monitor = None


def test_health_check_503_when_no_monitor(client, app_with_router):
    """E(Error): health_monitor 미설정 → POST /check → 503"""
    app_with_router.state.health_monitor = None

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.HEALTH_MONITOR_ENABLED = True

        response = client.post("/api/v1/health/check")

    assert response.status_code == 503


def test_health_alerts_empty_when_no_monitor(client, app_with_router):
    """B(Boundary): health_monitor 미설정 → GET /alerts → {"alerts": []}"""
    app_with_router.state.health_monitor = None

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.HEALTH_MONITOR_ENABLED = True

        response = client.get("/api/v1/health/alerts")

    assert response.status_code == 200
    assert response.json() == {"alerts": []}
