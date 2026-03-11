"""HTTP 통합 테스트 — cleanup-stale API (TestClient 기반)

Phase T5: POST /api/v1/dev-runner/runners/cleanup-stale 엔드포인트 검증
실제 Redis 없이 executor_service를 mock으로 교체하여 HTTP 레이어만 검증합니다.
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
    """cleanup_stale_runners()를 mock하는 패치 컨텍스트"""
    total = cleaned_active + cleaned_recent
    return patch(
        "app.modules.dev_runner.routes.runner.executor_service.cleanup_stale_runners",
        new_callable=AsyncMock,
        return_value={
            "cleaned_active": cleaned_active,
            "cleaned_recent": cleaned_recent,
            "bugs": bugs,
            "total": total,
        },
    )


class TestCleanupStaleEndpoint200:
    """POST /runners/cleanup-stale → 200 + success: true 검증"""

    def test_cleanup_stale_endpoint_returns_200(self, client):
        """정상 응답 200 + success: true + cleaned 필드 확인"""
        with _mock_cleanup_stale(cleaned_active=1, cleaned_recent=2):
            response = client.post(f"{BASE_URL}/runners/cleanup-stale")

        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data.get("cleaned") == 3
        assert "detail" in data
        assert data["detail"]["cleaned_active"] == 1
        assert data["detail"]["cleaned_recent"] == 2

    def test_cleanup_stale_endpoint_empty_returns_200(self, client):
        """정리 대상 없을 때도 200 + success: true + cleaned: 0"""
        with _mock_cleanup_stale(cleaned_active=0, cleaned_recent=0):
            response = client.post(f"{BASE_URL}/runners/cleanup-stale")

        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data.get("cleaned") == 0


class TestCleanupStaleEndpointIdempotent:
    """두 번 호출해도 동일한 응답 확인 (멱등성 검증)"""

    def test_cleanup_stale_endpoint_idempotent(self, client):
        """두 번 호출해도 동일한 응답 구조 반환"""
        with _mock_cleanup_stale(cleaned_active=0, cleaned_recent=1):
            response1 = client.post(f"{BASE_URL}/runners/cleanup-stale")

        with _mock_cleanup_stale(cleaned_active=0, cleaned_recent=0):
            response2 = client.post(f"{BASE_URL}/runners/cleanup-stale")

        assert response1.status_code == 200
        assert response2.status_code == 200

        data1 = response1.json()
        data2 = response2.json()

        # 두 응답 모두 동일한 스키마를 가져야 함
        assert data1.get("success") is True
        assert data2.get("success") is True
        assert "cleaned" in data1
        assert "cleaned" in data2
        assert "detail" in data1
        assert "detail" in data2

    def test_cleanup_stale_response_schema(self, client):
        """응답 JSON 스키마 검증 — 필수 필드 존재 확인"""
        with _mock_cleanup_stale(cleaned_active=2, cleaned_recent=1, bugs=1):
            response = client.post(f"{BASE_URL}/runners/cleanup-stale")

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data.get("success"), bool)
        assert isinstance(data.get("cleaned"), int)
        assert data["cleaned"] >= 0

        detail = data.get("detail", {})
        assert isinstance(detail.get("cleaned_active"), int)
        assert isinstance(detail.get("cleaned_recent"), int)
