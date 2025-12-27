"""
인증 시스템 단위 테스트

Google OAuth 인증 및 JWT 토큰 관련 테스트
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from jose import jwt

from app.main import app
from app.core.auth import (
    create_access_token,
    verify_token,
    is_admin_email,
    TokenData,
    UserInfo,
)
from app.core.config import settings


# TestClient 생성
client = TestClient(app)


class TestJWTToken:
    """JWT 토큰 생성/검증 테스트"""

    def test_create_access_token_basic(self):
        """기본 토큰 생성 테스트"""
        token = create_access_token(email="test@example.com", is_admin=False)
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_access_token_admin(self):
        """관리자 토큰 생성 테스트"""
        token = create_access_token(email="admin@example.com", is_admin=True)
        assert token is not None

        # 토큰 디코딩하여 is_admin 확인
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
        assert payload["is_admin"] is True
        assert payload["sub"] == "admin@example.com"

    def test_verify_token_valid(self):
        """유효한 토큰 검증 테스트"""
        token = create_access_token(email="test@example.com", is_admin=False)
        result = verify_token(token)

        assert result is not None
        assert isinstance(result, TokenData)
        assert result.email == "test@example.com"
        assert result.is_admin is False

    def test_verify_token_admin(self):
        """관리자 토큰 검증 테스트"""
        token = create_access_token(email="admin@example.com", is_admin=True)
        result = verify_token(token)

        assert result is not None
        assert result.is_admin is True

    def test_verify_token_invalid(self):
        """유효하지 않은 토큰 검증 테스트"""
        result = verify_token("invalid.token.here")
        assert result is None

    def test_verify_token_expired(self):
        """만료된 토큰 검증 테스트"""
        # 만료된 토큰 직접 생성
        expire = datetime.utcnow() - timedelta(hours=1)
        to_encode = {
            "sub": "test@example.com",
            "is_admin": False,
            "exp": expire
        }
        expired_token = jwt.encode(
            to_encode,
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM
        )

        result = verify_token(expired_token)
        assert result is None

    def test_verify_token_wrong_secret(self):
        """잘못된 시크릿으로 서명된 토큰 테스트"""
        expire = datetime.utcnow() + timedelta(hours=1)
        to_encode = {
            "sub": "test@example.com",
            "is_admin": False,
            "exp": expire
        }
        wrong_token = jwt.encode(
            to_encode,
            "wrong-secret-key",
            algorithm=settings.JWT_ALGORITHM
        )

        result = verify_token(wrong_token)
        assert result is None


class TestAdminEmail:
    """관리자 이메일 확인 테스트"""

    def test_is_admin_email_match(self):
        """관리자 이메일 일치 테스트"""
        with patch.object(settings, 'ADMIN_EMAIL', 'admin@example.com'):
            assert is_admin_email("admin@example.com") is True
            assert is_admin_email("ADMIN@EXAMPLE.COM") is True  # 대소문자 무시

    def test_is_admin_email_no_match(self):
        """관리자 이메일 불일치 테스트"""
        with patch.object(settings, 'ADMIN_EMAIL', 'admin@example.com'):
            assert is_admin_email("user@example.com") is False

    def test_is_admin_email_not_configured(self):
        """관리자 이메일 미설정 테스트"""
        with patch.object(settings, 'ADMIN_EMAIL', ''):
            assert is_admin_email("any@example.com") is False


class TestAuthMeEndpoint:
    """GET /api/v1/auth/me 엔드포인트 테스트"""

    def test_auth_me_localhost_auto_admin(self):
        """localhost에서는 토큰 없이도 자동 관리자 처리"""
        # TestClient는 localhost로 인식되므로 자동 관리자
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["email"] == "localhost@admin"
        assert data["user"]["isAdmin"] is True

    def test_auth_me_not_logged_in_external(self, mock_external_request):
        """외부 요청 비로그인 상태 테스트"""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["user"] is None

    def test_auth_me_valid_token(self):
        """유효한 토큰으로 사용자 정보 조회"""
        token = create_access_token(email="test@example.com", is_admin=False)
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["email"] == "test@example.com"
        assert data["user"]["isAdmin"] is False

    def test_auth_me_admin_token(self):
        """관리자 토큰으로 사용자 정보 조회"""
        token = create_access_token(email="admin@example.com", is_admin=True)
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["email"] == "admin@example.com"
        assert data["user"]["isAdmin"] is True

    def test_auth_me_invalid_token_localhost(self):
        """localhost에서 유효하지 않은 토큰 - 자동 관리자 처리"""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"}
        )
        assert response.status_code == 200
        data = response.json()
        # get_current_user는 유효한 토큰이면 user 반환, 아니면 None
        # localhost이고 user가 None이면 자동 관리자 처리
        assert data["user"]["email"] == "localhost@admin"
        assert data["user"]["isAdmin"] is True

    def test_auth_me_invalid_token_external(self, mock_external_request):
        """외부 요청에서 유효하지 않은 토큰 - None 반환"""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"] is None


class TestAuthLoginEndpoint:
    """GET /api/v1/auth/login 엔드포인트 테스트"""

    def test_auth_login_not_configured(self):
        """OAuth 미설정 상태 테스트"""
        with patch.object(settings, 'GOOGLE_CLIENT_ID', ''):
            response = client.get("/api/v1/auth/login", follow_redirects=False)
            assert response.status_code == 503
            data = response.json()
            assert "설정되지 않았습니다" in data["detail"]

    def test_auth_login_redirect(self):
        """OAuth 설정 시 리디렉트 테스트"""
        with patch.object(settings, 'GOOGLE_CLIENT_ID', 'test-client-id'):
            response = client.get("/api/v1/auth/login", follow_redirects=False)
            assert response.status_code == 307  # Temporary Redirect
            assert "accounts.google.com" in response.headers["location"]
            assert "test-client-id" in response.headers["location"]


class TestAuthLogoutEndpoint:
    """POST /api/v1/auth/logout 엔드포인트 테스트"""

    def test_auth_logout(self):
        """로그아웃 테스트"""
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        data = response.json()
        assert "로그아웃" in data["message"]


class TestRequireAdminDependency:
    """require_admin 의존성 테스트"""

    def test_require_admin_no_token(self):
        """토큰 없이 관리자 API 접근 시 401"""
        # 실제 관리자 전용 API가 있을 때 테스트
        # 현재는 API 보호가 아직 적용되지 않았으므로 skip
        pass

    def test_require_admin_non_admin_token(self):
        """일반 사용자 토큰으로 관리자 API 접근 시 403"""
        # 실제 관리자 전용 API가 있을 때 테스트
        # 현재는 API 보호가 아직 적용되지 않았으므로 skip
        pass


class TestLocalhostException:
    """localhost 예외 처리 테스트

    이 테스트는 DB fixture를 사용하는 test_event_api.py에서 테스트됩니다.
    여기서는 is_localhost_request 함수만 단위 테스트합니다.
    """

    def test_is_localhost_127_0_0_1(self):
        """127.0.0.1은 localhost로 인식"""
        from app.core.auth import is_localhost_request

        class MockClient:
            host = "127.0.0.1"

        class MockRequest:
            client = MockClient()
            headers = {}

        assert is_localhost_request(MockRequest()) is True

    def test_is_localhost_localhost(self):
        """localhost는 localhost로 인식"""
        from app.core.auth import is_localhost_request

        class MockClient:
            host = "localhost"

        class MockRequest:
            client = MockClient()
            headers = {}

        assert is_localhost_request(MockRequest()) is True

    def test_is_localhost_ipv6(self):
        """::1 (IPv6 localhost)은 localhost로 인식"""
        from app.core.auth import is_localhost_request

        class MockClient:
            host = "::1"

        class MockRequest:
            client = MockClient()
            headers = {}

        assert is_localhost_request(MockRequest()) is True

    def test_is_localhost_testclient(self):
        """testclient는 localhost로 인식"""
        from app.core.auth import is_localhost_request

        class MockClient:
            host = "testclient"

        class MockRequest:
            client = MockClient()
            headers = {}

        assert is_localhost_request(MockRequest()) is True

    def test_is_localhost_none_client(self):
        """client가 None인 경우 localhost로 인식 (TestClient 등)"""
        from app.core.auth import is_localhost_request

        class MockRequest:
            client = None
            headers = {}

        assert is_localhost_request(MockRequest()) is True

    def test_is_not_localhost_external_ip(self):
        """외부 IP는 localhost가 아님"""
        from app.core.auth import is_localhost_request

        class MockClient:
            host = "116.42.248.226"

        class MockRequest:
            client = MockClient()
            headers = {}

        assert is_localhost_request(MockRequest()) is False

    def test_is_not_localhost_domain(self):
        """도메인은 localhost가 아님"""
        from app.core.auth import is_localhost_request

        class MockClient:
            host = "monitor.woory.day"

        class MockRequest:
            client = MockClient()
            headers = {}

        assert is_localhost_request(MockRequest()) is False

    def test_is_not_localhost_cloudflare_tunnel(self):
        """Cloudflare Tunnel을 통한 요청은 localhost가 아님"""
        from app.core.auth import is_localhost_request

        class MockClient:
            host = "127.0.0.1"  # Tunnel은 localhost로 연결되지만

        class MockRequest:
            client = MockClient()
            headers = {"CF-Connecting-IP": "116.42.248.226"}  # 실제 클라이언트 IP

        assert is_localhost_request(MockRequest()) is False

    def test_is_localhost_without_cf_header(self):
        """CF-Connecting-IP 헤더 없는 localhost 요청"""
        from app.core.auth import is_localhost_request

        class MockClient:
            host = "127.0.0.1"

        class MockRequest:
            client = MockClient()
            headers = {}

        assert is_localhost_request(MockRequest()) is True


class TestCookieAuthentication:
    """Cookie 기반 인증 테스트

    PWA Share Target 등에서 localStorage 접근이 불가할 때
    Cookie를 통한 인증 fallback 동작을 테스트합니다.
    """

    def test_auth_me_cookie_only(self, mock_external_request):
        """Cookie만으로 인증 (Authorization 헤더 없음)"""
        token = create_access_token(email="cookie@example.com", is_admin=False)
        response = client.get(
            "/api/v1/auth/me",
            cookies={"auth_token": token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["email"] == "cookie@example.com"
        assert data["user"]["isAdmin"] is False

    def test_auth_me_cookie_admin(self, mock_external_request):
        """Cookie로 관리자 인증"""
        token = create_access_token(email="admin@example.com", is_admin=True)
        response = client.get(
            "/api/v1/auth/me",
            cookies={"auth_token": token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["email"] == "admin@example.com"
        assert data["user"]["isAdmin"] is True

    def test_auth_me_header_priority_over_cookie(self, mock_external_request):
        """Authorization 헤더가 Cookie보다 우선"""
        header_token = create_access_token(email="header@example.com", is_admin=True)
        cookie_token = create_access_token(email="cookie@example.com", is_admin=False)

        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {header_token}"},
            cookies={"auth_token": cookie_token}
        )
        assert response.status_code == 200
        data = response.json()
        # Authorization 헤더의 토큰이 사용됨
        assert data["user"]["email"] == "header@example.com"
        assert data["user"]["isAdmin"] is True

    def test_auth_me_invalid_cookie(self, mock_external_request):
        """유효하지 않은 Cookie - 인증 실패"""
        response = client.get(
            "/api/v1/auth/me",
            cookies={"auth_token": "invalid.token.here"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"] is None

    def test_auth_me_expired_cookie(self, mock_external_request):
        """만료된 Cookie 토큰 - 인증 실패"""
        # 만료된 토큰 생성
        expire = datetime.utcnow() - timedelta(hours=1)
        to_encode = {
            "sub": "expired@example.com",
            "is_admin": False,
            "exp": expire
        }
        expired_token = jwt.encode(
            to_encode,
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM
        )

        response = client.get(
            "/api/v1/auth/me",
            cookies={"auth_token": expired_token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"] is None

    def test_auth_me_fallback_to_cookie_when_header_invalid(self, mock_external_request):
        """Authorization 헤더가 유효하지 않으면 Cookie fallback"""
        cookie_token = create_access_token(email="cookie@example.com", is_admin=True)

        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.header.token"},
            cookies={"auth_token": cookie_token}
        )
        assert response.status_code == 200
        data = response.json()
        # 헤더가 유효하지 않으면 Cookie 사용
        assert data["user"]["email"] == "cookie@example.com"
        assert data["user"]["isAdmin"] is True
