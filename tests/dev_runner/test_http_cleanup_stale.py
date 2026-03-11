"""HTTP E2E TC — cleanup-stale API (TestClient 기반)

Phase T4: POST /api/v1/dev-runner/runners/cleanup-stale 엔드포인트 검증
실제 Redis 없이 executor_service.cleanup_stale_runners를 mock으로 교체하여 HTTP 레이어만 검증합니다.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app

BASE_URL = "/api/v1/dev-runner"


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드 — plan_service 의존성 없음"""
    yield


@pytest.fixture
def client():
    """TestClient — DB/Redis 연결 없이 HTTP 레이어 테스트"""
    return TestClient(app, raise_server_exceptions=True)


def _mock_cleanup_stale(cleaned_active: int = 0, cleaned_recent: int = 0, bugs: int = 0):
    """cleanup_stale_runners()를 mock하여 지정된 결과를 반환하는 패치 컨텍스트"""
    return patch(
        "app.modules.dev_runner.routes.runner.executor_service.cleanup_stale_runners",
        new_callable=AsyncMock,
        return_value={
            "success": True,
            "cleaned_active": cleaned_active,
            "cleaned_recent": cleaned_recent,
            "bugs": bugs,
        },
    )


class TestHttpCleanupStaleSuccess:
    """POST /runners/cleanup-stale 200 응답 및 cleaned 카운트 검증"""

    def test_cleanup_stale_post_returns_success(self, client):
        """mock executor → POST /runners/cleanup-stale → 200 + {"success": True, "cleaned_active": N}"""
        with _mock_cleanup_stale(cleaned_active=2, cleaned_recent=1):
            response = client.post(f"{BASE_URL}/runners/cleanup-stale")

        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data.get("cleaned_active") == 2
        assert data.get("cleaned_recent") == 1

    def test_cleanup_stale_post_empty_result(self, client):
        """정리 대상 없을 때 → 200 + cleaned=0 (에러 아님)"""
        with _mock_cleanup_stale(cleaned_active=0, cleaned_recent=0):
            response = client.post(f"{BASE_URL}/runners/cleanup-stale")

        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data.get("cleaned_active") == 0
        assert data.get("cleaned_recent") == 0
