"""
인증 라우트

Google OAuth를 통한 관리자 로그인/로그아웃 처리
"""

import secrets
from urllib.parse import urlencode
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends, Response, Request
from fastapi.responses import RedirectResponse
import httpx
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.core.config import settings, logger
from app.core.auth import (
    create_access_token,
    get_current_user,
    is_admin_email,
    is_localhost_request,
    verify_token,
    UserInfo,
)


router = APIRouter(prefix="/auth", tags=["인증"])

# 상태 토큰 서명을 위한 시리얼라이저
_serializer = URLSafeTimedSerializer(settings.JWT_SECRET)

# Google OAuth 엔드포인트
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def _get_callback_url(request: Request) -> str:
    """OAuth redirect_uri single source를 반환한다.

    Admin login도 Google callback 자체는 public API 도메인에서만 받고,
    callback 완료 후 landing URL만 admin/public으로 나눈다.
    """
    # API_BASE_URL이 설정되어 있으면 OAuth redirect_uri single source로 사용한다.
    if settings.API_BASE_URL:
        return f"{settings.API_BASE_URL.rstrip('/')}/auth/callback"
    # 그렇지 않으면 요청 기반으로 생성 (로컬 개발용)
    return str(request.url_for("auth_callback"))


@router.get("/login")
async def auth_login(request: Request):
    """
    Google OAuth 로그인 시작

    Google 로그인 페이지로 리디렉트합니다.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth가 설정되지 않았습니다. GOOGLE_CLIENT_ID를 설정해주세요."
        )

    # CSRF 방지를 위한 상태 토큰 생성
    state = _serializer.dumps(secrets.token_urlsafe(16))

    # Google OAuth URL 생성
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        # 로그인 시작 host와 관계없이 redirect_uri는 _get_callback_url()만 사용한다.
        "redirect_uri": _get_callback_url(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",  # 항상 계정 선택 화면 표시
    }

    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    logger.info(f"OAuth 로그인 시작: redirect_uri={_get_callback_url(request)}")

    return RedirectResponse(url=auth_url)


@router.get("/callback", name="auth_callback")
async def auth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """
    Google OAuth 콜백 처리

    Google에서 인증 후 이 엔드포인트로 리디렉트됩니다.
    JWT 토큰을 생성하고 프론트엔드로 리디렉트합니다.
    """
    # 에러 처리
    if error:
        logger.warning(f"OAuth 에러: {error}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/login?error={error}"
        )

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="인증 코드 또는 상태가 없습니다"
        )

    # 상태 토큰 검증 (5분 이내)
    try:
        _serializer.loads(state, max_age=300)
    except (BadSignature, SignatureExpired):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않거나 만료된 상태 토큰입니다"
        )

    # Google에서 액세스 토큰 요청
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": _get_callback_url(request),
            },
        )

        if token_response.status_code != 200:
            logger.error(f"토큰 요청 실패: {token_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google 토큰 요청 실패"
            )

        token_data = token_response.json()
        access_token = token_data.get("access_token")

        # 사용자 정보 요청
        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if userinfo_response.status_code != 200:
            logger.error(f"사용자 정보 요청 실패: {userinfo_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google 사용자 정보 요청 실패"
            )

        user_info = userinfo_response.json()
        email = user_info.get("email")

        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이메일 정보를 가져올 수 없습니다"
            )

    # 관리자 여부 확인
    is_admin = is_admin_email(email)
    logger.info(f"OAuth 로그인 성공: email={email}, is_admin={is_admin}")

    # JWT 토큰 생성
    jwt_token = create_access_token(email=email, is_admin=is_admin)

    # callback host는 public API single source를 유지하고, callback 완료 후 landing만 분기한다.
    if is_admin:
        redirect_url = f"https://dev-monitor.woory.day/auth/callback?token={jwt_token}"
    else:
        redirect_url = f"{settings.FRONTEND_URL}/auth/callback?token={jwt_token}"

    response = RedirectResponse(url=redirect_url)

    # PWA 공유 기능 등에서 localStorage 접근 불가 시를 위해 Cookie에도 토큰 저장
    # SameSite=Lax: CSRF 방지하면서 top-level navigation에서는 전송
    # domain=.woory.day: 모든 서브도메인에서 Cookie 공유 (dev-monitor, monitor 등)
    response.set_cookie(
        key="auth_token",
        value=jwt_token,
        max_age=settings.JWT_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=True,  # HTTPS에서만 전송
        path="/",  # 모든 경로에서 전송 (프록시 경유 시에도)
        domain=".woory.day",  # 서브도메인 공유
    )

    return response


@router.get("/me")
async def auth_me(
    request: Request,
    user: Optional[UserInfo] = Depends(get_current_user)
):
    """
    현재 로그인한 사용자 정보 조회

    localhost 요청의 경우 자동으로 관리자로 처리됩니다.
    Authorization 헤더 또는 Cookie에서 토큰을 확인합니다.

    Returns:
        사용자 정보 또는 null (비로그인 시)
    """
    # localhost 요청은 자동 관리자 처리
    if user is None and is_localhost_request(request):
        return {
            "user": {
                "email": "localhost@admin",
                "isAdmin": True,
            }
        }

    # Authorization 헤더에 토큰이 없으면 Cookie에서 확인 (PWA 공유 기능 등)
    if user is None:
        cookie_token = request.cookies.get("auth_token")
        if cookie_token:
            token_data = verify_token(cookie_token)
            if token_data:
                user = UserInfo(email=token_data.email, is_admin=token_data.is_admin)

    if user is None:
        return {"user": None}

    return {
        "user": {
            "email": user.email,
            "isAdmin": user.is_admin,
        }
    }


@router.post("/logout")
async def auth_logout(response: Response):
    """
    로그아웃

    Cookie에 저장된 토큰을 삭제합니다.
    클라이언트 측에서는 localStorage의 토큰도 삭제해야 합니다.
    """
    response.delete_cookie(
        key="auth_token",
        path="/",
        domain=".woory.day",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return {"message": "로그아웃되었습니다"}
