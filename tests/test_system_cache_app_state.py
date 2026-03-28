"""
system/routes.py app.state 참조 패턴 검증 테스트

모듈 전역 변수(_cache_collector) 제거 후 request.app.state.system_cache_collector 참조로
올바르게 동작하는지 확인한다.
"""
import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

os.environ.setdefault("TESTING", "1")


@pytest.fixture
def app_with_router():
    from fastapi import FastAPI
    from app.modules.system.routes import router

    app = FastAPI()
    app.state.system_cache_collector = None
    app.include_router(router)
    return app


@pytest.fixture
def client(app_with_router):
    from fastapi.testclient import TestClient
    return TestClient(app_with_router)


def test_services_status_without_collector(client, app_with_router):
    """R(Right): system_cache_collector 미설정 → fallback 직접 수집 호출"""
    app_with_router.state.system_cache_collector = None

    with patch("app.modules.system.routes._service") as mock_service:
        mock_service.get_all_services_status = AsyncMock(return_value={"projects": []})

        response = client.get("/api/v1/system/services/status")

    assert response.status_code == 200
    mock_service.get_all_services_status.assert_called_once()


def test_refresh_503_without_collector(client, app_with_router):
    """E(Error): system_cache_collector 미설정 → POST /refresh → 503"""
    app_with_router.state.system_cache_collector = None

    response = client.post("/api/v1/system/services/refresh")

    assert response.status_code == 503


def test_services_status_with_collector(client, app_with_router):
    """R(Right): app.state.system_cache_collector 설정 후 → 캐시 데이터 반환"""
    mock_collector = MagicMock()
    mock_collector.get_cached_status.return_value = {
        "projects": [{"name": "test"}],
        "collected_at": "2026-03-29T10:00:00",
        "collection_duration_ms": 123,
    }
    app_with_router.state.system_cache_collector = mock_collector

    response = client.get("/api/v1/system/services/status")

    assert response.status_code == 200
    data = response.json()
    assert data["projects"][0]["name"] == "test"
    mock_collector.get_cached_status.assert_called_once()

    app_with_router.state.system_cache_collector = None
