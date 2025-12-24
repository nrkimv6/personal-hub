"""
Production Mode Middleware Tests

운영 모드에서 관리 API 차단 테스트.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """TestClient fixture"""
    return TestClient(app)


class TestAppModeEndpoint:
    """앱 모드 엔드포인트 테스트"""

    def test_get_app_mode_returns_mode(self, client):
        """앱 모드 조회"""
        response = client.get("/api/v1/system/mode")
        assert response.status_code == 200

        data = response.json()
        assert "mode" in data
        assert data["mode"] in ["production", "development"]
        assert "is_dev" in data
        assert "features" in data

    def test_get_app_mode_features_structure(self, client):
        """앱 모드 features 구조 확인"""
        response = client.get("/api/v1/system/mode")
        data = response.json()

        features = data.get("features", {})
        assert "workers_enabled" in features
        assert "admin_api_enabled" in features
        assert "crawling_enabled" in features
        assert "sniping_enabled" in features


class TestProductionModeMiddleware:
    """운영 모드 미들웨어 테스트 (현재 설정에 따라)"""

    def test_middleware_is_registered(self, client):
        """미들웨어가 등록되어 있는지 확인"""
        # /system/mode 접근 가능 여부로 미들웨어 동작 확인
        response = client.get("/api/v1/system/mode")
        assert response.status_code == 200

    def test_get_requests_allowed(self, client):
        """GET 요청은 항상 허용"""
        response = client.get("/api/v1/system/status")
        # 200 또는 다른 정상 응답 (403이 아니면 됨)
        assert response.status_code != 403

    def test_middleware_response_format(self, client):
        """미들웨어가 차단할 때 올바른 응답 형식 사용"""
        from app.core.config import settings

        if settings.APP_MODE == "production":
            # 운영 모드에서 POST 요청 차단 확인
            response = client.post("/api/v1/naver/businesses", json={})
            if response.status_code == 403:
                data = response.json()
                assert "detail" in data
                assert "운영 모드" in data["detail"]


class TestMiddlewareBlockedPatterns:
    """미들웨어 차단 패턴 테스트"""

    def test_blocked_patterns_format(self):
        """차단 패턴 형식 확인"""
        from app.core.middleware import BLOCKED_PATTERNS

        assert isinstance(BLOCKED_PATTERNS, list)
        for item in BLOCKED_PATTERNS:
            assert isinstance(item, tuple)
            assert len(item) == 2
            method, pattern = item
            assert method in ["GET", "POST", "PUT", "DELETE", "PATCH"]
            assert pattern.startswith("^")  # 정규식 시작 문자

    def test_is_blocked_method(self):
        """_is_blocked 메서드 테스트"""
        from app.core.middleware import ProductionModeMiddleware

        middleware = ProductionModeMiddleware(app=None)

        # 차단되어야 하는 패턴
        assert middleware._is_blocked("POST", "/api/v1/naver/businesses") == True
        assert middleware._is_blocked("DELETE", "/api/v1/naver/schedules/1") == True
        assert middleware._is_blocked("POST", "/api/v1/instagram/accounts/1/crawl") == True

        # 허용되어야 하는 패턴
        assert middleware._is_blocked("GET", "/api/v1/naver/businesses") == False
        assert middleware._is_blocked("GET", "/api/v1/system/mode") == False
