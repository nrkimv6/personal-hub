"""
Production Mode Middleware

운영 모드에서 비관리자의 쓰기 작업을 제한하는 미들웨어.

권한 매트릭스:
- 운영 + 비관리자: 이벤트 관리, 인증, GET만 허용
- 운영 + 관리자: 모든 API 허용 (워커는 별도로 비활성화)
- 개발 + localhost: 자동 관리자로 모든 API 허용
- 개발 + 비-localhost: 로그인에 따름
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import re
from app.core.config import settings
from app.core.auth import verify_token, is_localhost_request

# 운영 모드에서 비관리자에게 허용할 API 패턴 (화이트리스트)
ALLOWED_WRITE_PATTERNS_FOR_ANONYMOUS = [
    # 이벤트 관리 API
    r"^/api/v1/events",
    r"^/api/v1/popups",
    r"^/api/v1/uncategorized",
    # 인증 API
    r"^/api/v1/auth",
]

# 항상 허용하는 메서드 (읽기 전용)
ALWAYS_ALLOWED_METHODS = {"GET", "HEAD", "OPTIONS"}


class ProductionModeMiddleware(BaseHTTPMiddleware):
    """
    운영 모드에서 비관리자의 쓰기 작업을 제한하는 미들웨어.

    정책:
    - 개발 모드: 모든 기능 허용
    - 운영 모드 + 관리자: 모든 API 허용
    - 운영 모드 + 비관리자: 이벤트 관리, 인증, GET만 허용
    """

    async def dispatch(self, request: Request, call_next):
        # 개발 모드에서는 모든 기능 허용
        if settings.APP_MODE == "development":
            return await call_next(request)

        # 읽기 전용 메서드는 항상 허용
        if request.method in ALWAYS_ALLOWED_METHODS:
            return await call_next(request)

        # 관리자 여부 확인
        if self._is_admin(request):
            return await call_next(request)

        # 비관리자 - 화이트리스트 확인
        if self._is_allowed_for_anonymous(request.url.path):
            return await call_next(request)

        # 차단
        return JSONResponse(
            status_code=403,
            content={
                "detail": "운영 모드에서는 관리자 로그인이 필요합니다.",
                "mode": settings.APP_MODE,
                "blocked_action": f"{request.method} {request.url.path}",
                "hint": "관리자로 로그인하거나 개발 모드(-Dev)에서 실행하세요."
            }
        )

    def _is_admin(self, request: Request) -> bool:
        """
        요청자가 관리자인지 확인.

        - localhost 요청은 자동 관리자 (개발 편의)
        - JWT 토큰에서 is_admin=True면 관리자
        """
        # localhost는 자동 관리자
        if is_localhost_request(request):
            return True

        # Authorization 헤더에서 토큰 추출
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return False

        token = auth_header[7:]  # "Bearer " 이후
        token_data = verify_token(token)

        if token_data and token_data.is_admin:
            return True

        return False

    def _is_allowed_for_anonymous(self, path: str) -> bool:
        """
        경로가 비관리자 화이트리스트에 포함되는지 확인.
        """
        for pattern in ALLOWED_WRITE_PATTERNS_FOR_ANONYMOUS:
            if re.match(pattern, path):
                return True
        return False
