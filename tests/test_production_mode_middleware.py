"""
API Access Control Middleware Tests

모든 모드에서 권한에 따른 API 접근 제어 테스트.

권한 매트릭스:
- GET/HEAD/OPTIONS: 항상 허용
- localhost: 자동 관리자로 모든 API 허용
- 관리자 로그인: 모든 API 허용
- 비관리자: 이벤트 관리, 인증만 허용 (모드 무관)
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.core.auth import create_access_token


@pytest.fixture
def client():
    """TestClient fixture"""
    return TestClient(app)


@pytest.fixture
def admin_token():
    """관리자 JWT 토큰"""
    return create_access_token(email="admin@test.com", is_admin=True)


@pytest.fixture
def user_token():
    """일반 사용자 JWT 토큰"""
    return create_access_token(email="user@test.com", is_admin=False)


class TestAppModeEndpoint:
    """앱 모드 엔드포인트 테스트"""

    def test_get_app_mode_returns_mode(self, client):
        """앱 모드 조회"""
        response = client.get("/api/v1/system/mode")
        assert response.status_code == 200

        data = response.json()
        assert "mode" in data
        assert data["mode"] in ["public", "admin"]
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
    """운영 모드 미들웨어 테스트"""

    def test_get_requests_always_allowed(self, client):
        """GET 요청은 항상 허용"""
        response = client.get("/api/v1/system/status")
        assert response.status_code != 403

    @patch("app.core.middleware.settings")
    def test_production_anonymous_blocked_naver_post(self, mock_settings, client):
        """운영 모드에서 비관리자는 naver API POST 차단"""
        mock_settings.APP_MODE = "public"

        # 비관리자 (토큰 없음, localhost 아님)
        response = client.post(
            "/api/v1/naver/businesses",
            json={},
            headers={"CF-Connecting-IP": "1.2.3.4"}  # 외부 IP로 가장
        )
        assert response.status_code == 403
        data = response.json()
        assert "관리자 로그인" in data["detail"]

    @patch("app.core.middleware.settings")
    def test_production_anonymous_allowed_events_post(self, mock_settings, client):
        """운영 모드에서 비관리자도 events API POST 허용"""
        mock_settings.APP_MODE = "public"

        response = client.post(
            "/api/v1/events",
            json={"title": "test"},
            headers={"CF-Connecting-IP": "1.2.3.4"}
        )
        # 403이 아니면 됨 (validation error 등은 허용)
        assert response.status_code != 403

    @patch("app.core.middleware.settings")
    def test_production_anonymous_allowed_popups_post(self, mock_settings, client):
        """운영 모드에서 비관리자도 popups API POST 허용"""
        mock_settings.APP_MODE = "public"

        response = client.post(
            "/api/v1/popups",
            json={"title": "test"},
            headers={"CF-Connecting-IP": "1.2.3.4"}
        )
        assert response.status_code != 403

    @patch("app.core.middleware.settings")
    def test_production_anonymous_allowed_auth_post(self, mock_settings, client):
        """운영 모드에서 비관리자도 auth API POST 허용"""
        mock_settings.APP_MODE = "public"

        response = client.post(
            "/api/v1/auth/logout",
            headers={"CF-Connecting-IP": "1.2.3.4"}
        )
        assert response.status_code != 403

    @patch("app.core.middleware.settings")
    def test_production_admin_allowed_all(self, mock_settings, client, admin_token):
        """운영 모드에서 관리자는 모든 API 허용"""
        mock_settings.APP_MODE = "public"

        response = client.post(
            "/api/v1/naver/businesses",
            json={},
            headers={
                "Authorization": f"Bearer {admin_token}",
                "CF-Connecting-IP": "1.2.3.4"
            }
        )
        # 403이 아니면 됨 (다른 오류는 허용)
        assert response.status_code != 403

    @patch("app.core.middleware.settings")
    def test_production_localhost_treated_as_admin(self, mock_settings, client):
        """운영 모드에서 localhost는 자동 관리자"""
        mock_settings.APP_MODE = "public"

        # localhost 요청 (CF-Connecting-IP 없음)
        response = client.post(
            "/api/v1/naver/businesses",
            json={}
        )
        # 403이 아니면 됨
        assert response.status_code != 403

    @patch("app.core.middleware.settings")
    def test_development_anonymous_blocked(self, mock_settings, client):
        """개발 모드에서도 비관리자는 차단"""
        mock_settings.APP_MODE = "admin"

        response = client.post(
            "/api/v1/naver/businesses",
            json={},
            headers={"CF-Connecting-IP": "1.2.3.4"}  # 외부 IP로 가장
        )
        # 비관리자는 403
        assert response.status_code == 403

    @patch("app.core.middleware.settings")
    def test_development_localhost_allowed(self, mock_settings, client):
        """개발 모드에서 localhost는 자동 관리자"""
        mock_settings.APP_MODE = "admin"

        # localhost 요청 (CF-Connecting-IP 없음)
        response = client.post(
            "/api/v1/naver/businesses",
            json={}
        )
        # 403이 아니면 됨
        assert response.status_code != 403

    @patch("app.core.middleware.settings")
    def test_development_admin_allowed(self, mock_settings, client, admin_token):
        """개발 모드에서 관리자는 모든 API 허용"""
        mock_settings.APP_MODE = "admin"

        response = client.post(
            "/api/v1/naver/businesses",
            json={},
            headers={
                "Authorization": f"Bearer {admin_token}",
                "CF-Connecting-IP": "1.2.3.4"
            }
        )
        # 403이 아니면 됨
        assert response.status_code != 403


class TestMiddlewareHelperMethods:
    """미들웨어 헬퍼 메서드 테스트"""

    def test_is_allowed_for_anonymous_events(self):
        """비관리자 화이트리스트 - events"""
        from app.core.middleware import ProductionModeMiddleware

        middleware = ProductionModeMiddleware(app=None)

        assert middleware._is_allowed_for_anonymous("/api/v1/events") == True
        assert middleware._is_allowed_for_anonymous("/api/v1/events/1") == True
        assert middleware._is_allowed_for_anonymous("/api/v1/popups") == True
        assert middleware._is_allowed_for_anonymous("/api/v1/uncategorized") == True
        assert middleware._is_allowed_for_anonymous("/api/v1/auth/login") == True

    def test_is_allowed_for_anonymous_blocked(self):
        """비관리자 화이트리스트 - 차단되는 경로"""
        from app.core.middleware import ProductionModeMiddleware

        middleware = ProductionModeMiddleware(app=None)

        assert middleware._is_allowed_for_anonymous("/api/v1/naver/businesses") == False
        assert middleware._is_allowed_for_anonymous("/api/v1/instagram/accounts") == False
        assert middleware._is_allowed_for_anonymous("/api/v1/worker/start") == False


class TestMiddlewareIntegration:
    """미들웨어 통합 테스트"""

    def test_middleware_response_format(self, client):
        """미들웨어 차단 시 응답 형식"""
        from app.core.config import settings

        if settings.APP_MODE == "public":
            response = client.post(
                "/api/v1/naver/businesses",
                json={},
                headers={"CF-Connecting-IP": "1.2.3.4"}
            )
            if response.status_code == 403:
                data = response.json()
                assert "detail" in data
                assert "mode" in data
                assert "blocked_action" in data
                assert "hint" in data

    def test_allowed_write_patterns_structure(self):
        """화이트리스트 패턴 구조 확인"""
        from app.core.middleware import ALLOWED_WRITE_PATTERNS_FOR_ANONYMOUS

        assert isinstance(ALLOWED_WRITE_PATTERNS_FOR_ANONYMOUS, list)
        for pattern in ALLOWED_WRITE_PATTERNS_FOR_ANONYMOUS:
            assert isinstance(pattern, str)
            assert pattern.startswith("^")
