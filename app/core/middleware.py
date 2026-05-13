"""
API Access Control Middleware

모든 모드(운영/개발)에서 비관리자의 쓰기 작업을 제한하는 미들웨어.

권한 매트릭스:
- GET/HEAD/OPTIONS: localhost/admin은 허용, public 외부 요청은 public-safe/admin-only 분류
- localhost: 자동 관리자로 모든 API 허용
- 관리자 로그인: 모든 API 허용
- 비관리자: 이벤트 관리, 인증만 허용

워커 동작:
- 운영 모드: 워커 비활성화 (main.py에서 처리)
- 개발 모드: 워커 활성화, 운영에서 등록된 작업도 DB 폴링하여 실행
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import re
from app.core.config import get_runtime_app_mode, settings, logger
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

# Public-safe read prefixes are product or health surfaces that must work
# without admin auth in public mode. Keep this list narrow and add a comment
# here when a new public GET surface is intentionally exposed.
PUBLIC_SAFE_READ_PREFIXES = (
    "/api/v1/auth",
    "/api/v1/health",
    "/api/v1/system/liveness",
    "/api/v1/system/mode",
    "/api/v1/events",
    "/api/v1/popups",
    "/api/v1/uncategorized",
    "/api/v1/monitoring/events/coupang-public-history",
    "/api/v1/expo",
    "/api/v1/expo/maps",
)

# Admin-only read prefixes expose local files, runners, process/service state,
# plans, git repositories, search/scan status, or LLM/worker internals.
ADMIN_ONLY_READ_PREFIXES = (
    "/api/v1/dev-runner",
    "/api/v1/plans",
    "/api/v1/git-repos",
    "/api/v1/file-search",
    "/api/v1/test-runs",
    "/api/v1/claude-sessions",
    "/api/v1/system",
    "/api/v1/worker",
    "/api/v1/llm",
    "/api/v1/ss",
    "/api/ic",
    "/api/fc",
    "/api/v1/list-board",  # list board admin only
)


def _path_matches_prefix(path: str, prefix: str) -> bool:
    """Match a route prefix on a path-segment boundary."""
    return path == prefix or path.startswith(f"{prefix}/")


def is_public_safe_read_path(path: str) -> bool:
    return any(_path_matches_prefix(path, prefix) for prefix in PUBLIC_SAFE_READ_PREFIXES)


def is_admin_only_read_path(path: str) -> bool:
    if is_public_safe_read_path(path):
        return False
    return any(_path_matches_prefix(path, prefix) for prefix in ADMIN_ONLY_READ_PREFIXES)


class ProductionModeMiddleware(BaseHTTPMiddleware):
    """
    비관리자의 쓰기 작업을 제한하는 미들웨어.

    정책:
    - 읽기 전용(GET/HEAD/OPTIONS): localhost/admin은 허용, public 외부 요청은 public-safe/admin-only 분류
    - localhost: 자동 관리자로 모든 API 허용
    - 관리자 로그인: 모든 API 허용
    - 비관리자:
      - Public 모드: 이벤트 관리, 인증만 허용
      - Admin 모드: 이벤트 관리, 인증만 허용 (관리자 로그인 필요)
    """

    async def dispatch(self, request: Request, call_next):
        # 읽기 전용 메서드는 public-safe allowlist와 admin-only 분류를 먼저 통과한다.
        if request.method in ALWAYS_ALLOWED_METHODS:
            if self._is_admin(request):
                return await call_next(request)
            if self._is_public_admin_only_read(request):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "관리자 로그인이 필요합니다.",
                        "mode": get_runtime_app_mode(settings_app_mode=settings.APP_MODE),
                        "blocked_action": f"{request.method} {request.url.path}",
                        "hint": "관리자로 로그인하세요.",
                    },
                )
            return await call_next(request)

        # 관리자 여부 확인 (localhost 포함)
        if self._is_admin(request):
            return await call_next(request)

        # 비관리자 - 화이트리스트 확인
        if self._is_allowed_for_anonymous(request.url.path):
            return await call_next(request)

        # 차단
        return JSONResponse(
            status_code=403,
            content={
                "detail": "관리자 로그인이 필요합니다.",
                "mode": get_runtime_app_mode(settings_app_mode=settings.APP_MODE),
                "blocked_action": f"{request.method} {request.url.path}",
                "hint": "관리자로 로그인하세요."
            }
        )

    def _is_admin(self, request: Request) -> bool:
        """
        요청자가 관리자인지 확인.

        - localhost 요청은 자동 관리자 (개발 편의)
        - JWT 토큰에서 is_admin=True면 관리자
        - Authorization 헤더 또는 Cookie에서 토큰 확인
        """
        # localhost는 자동 관리자
        if is_localhost_request(request):
            return True

        token = None
        token_source = None

        # 1. Authorization 헤더에서 토큰 추출 (우선)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]  # "Bearer " 이후
            token_source = "header"

        # 2. 헤더에 없으면 Cookie에서 토큰 추출 (PWA 공유 기능 등)
        if not token:
            token = request.cookies.get("auth_token")
            if token:
                token_source = "cookie"

        # 디버깅 로그 (POST/PUT/DELETE 요청만)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            logger.info(
                f"[Auth] {request.method} {request.url.path} | "
                f"token_source={token_source} | "
                f"has_auth_header={bool(auth_header)} | "
                f"cookies={list(request.cookies.keys())}"
            )

        if not token:
            return False

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

    def _is_public_admin_only_read(self, request: Request) -> bool:
        """Public 외부 요청에서 admin-only read surface를 읽지 못하게 한다."""
        if get_runtime_app_mode(settings_app_mode=settings.APP_MODE) != "public":
            return False
        return is_admin_only_read_path(request.url.path)
