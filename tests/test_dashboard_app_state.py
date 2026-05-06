"""
dashboard.py app 전달 패턴 검증 테스트

get_service_health(app), get_recent_alerts(app)이 app.state.health_monitor를
올바르게 참조하는지 확인한다.
"""
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "1")

pytestmark = pytest.mark.http


@pytest.fixture
def app_with_router():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.dashboard import router
    from app.database import get_db

    app = FastAPI()
    app.state.health_monitor = None

    # DB 의존성 mock
    mock_db = MagicMock()
    mock_db.execute.return_value.fetchone.return_value = None
    mock_db.execute.return_value.fetchall.return_value = []
    mock_db.execute.return_value.mappings.return_value.first.return_value = None
    mock_db.execute.return_value.mappings.return_value.all.return_value = []
    app.dependency_overrides[get_db] = lambda: mock_db

    app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture
def client(app_with_router):
    from fastapi.testclient import TestClient
    return TestClient(app_with_router)


def test_unified_dashboard_no_monitor(client, app_with_router):
    """R(Right): health_monitor 미설정 → GET /unified → 200 + service_health: {}"""
    app_with_router.state.health_monitor = None

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.HEALTH_MONITOR_ENABLED = True

        response = client.get("/api/v1/dashboard/unified")

    assert response.status_code == 200
    data = response.json()
    assert data["service_health"] == {}
    assert data["recent_alerts"] == []


def test_unified_dashboard_with_mock_monitor(client, app_with_router):
    """R(Right): app.state.health_monitor 설정 후 → service_health에 mock 데이터 포함"""
    mock_monitor = MagicMock()
    mock_monitor.get_all_services_status.return_value = {
        "api": {"status": "healthy", "last_check": "2026-03-29T10:00:00", "failure_count": 0}
    }
    mock_monitor.get_recent_alerts.return_value = []
    app_with_router.state.health_monitor = mock_monitor

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.HEALTH_MONITOR_ENABLED = True

        response = client.get("/api/v1/dashboard/unified")

    assert response.status_code == 200
    data = response.json()
    assert "api" in data["service_health"]

    app_with_router.state.health_monitor = None
