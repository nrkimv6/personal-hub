"""
Production Mode Middleware

운영 모드에서 관리 기능(쓰기 작업)을 차단하는 미들웨어.
개발 모드(APP_MODE=development)에서는 모든 기능 허용.
"""
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import re
from app.core.config import settings

# 운영 모드에서 차단할 패턴 (method, path_pattern)
# path_pattern은 정규식 패턴
BLOCKED_PATTERNS = [
    # Naver Booking - 모든 쓰기 작업
    ("POST", r"^/api/v1/naver/"),
    ("PUT", r"^/api/v1/naver/"),
    ("DELETE", r"^/api/v1/naver/"),
    ("PATCH", r"^/api/v1/naver/"),

    # Instagram - 크롤링, 분석 실행
    ("POST", r"^/api/v1/instagram/accounts/\d+/crawl"),
    ("POST", r"^/api/v1/instagram/posts/\d+/analyze"),
    ("POST", r"^/api/v1/instagram/accounts$"),  # 계정 생성
    ("PUT", r"^/api/v1/instagram/accounts/"),
    ("DELETE", r"^/api/v1/instagram/accounts/"),
    ("POST", r"^/api/v1/instagram/scheduler/"),
    ("PUT", r"^/api/v1/instagram/scheduler/"),
    ("DELETE", r"^/api/v1/instagram/scheduler/"),

    # Worker 관리
    ("POST", r"^/api/v1/worker/"),
    ("PUT", r"^/api/v1/worker/"),
    ("DELETE", r"^/api/v1/worker/"),

    # 프록시 관리
    ("POST", r"^/api/v1/proxy/"),
    ("PUT", r"^/api/v1/proxy/"),
    ("DELETE", r"^/api/v1/proxy/"),
]


class ProductionModeMiddleware(BaseHTTPMiddleware):
    """
    운영 모드에서 관리 기능을 차단하는 미들웨어.
    """

    async def dispatch(self, request: Request, call_next):
        # 개발 모드에서는 모든 기능 허용
        if settings.APP_MODE == "development":
            return await call_next(request)

        # 운영 모드에서 차단 여부 확인
        if self._is_blocked(request.method, request.url.path):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "이 기능은 운영 모드에서 비활성화되어 있습니다.",
                    "mode": settings.APP_MODE,
                    "blocked_action": f"{request.method} {request.url.path}"
                }
            )

        return await call_next(request)

    def _is_blocked(self, method: str, path: str) -> bool:
        """
        요청이 차단 대상인지 확인.
        """
        for blocked_method, pattern in BLOCKED_PATTERNS:
            if method == blocked_method and re.match(pattern, path):
                return True
        return False
