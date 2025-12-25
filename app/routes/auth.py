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
    """OAuth 콜백 URL 생성"""
    # API_BASE_URL이 설정되어 있으면 사용 (Cloudflare Tunnel 등 외부 접속용)
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

    # 프론트엔드로 리디렉트 (토큰을 쿼리 파라미터로 전달)
    # 관리자인 경우 dev 환경으로 리다이렉트
    if is_admin:
        redirect_url = f"https://dev-monitor.woory.day/auth/callback?token={jwt_token}"
    else:
        redirect_url = f"{settings.FRONTEND_URL}/auth/callback?token={jwt_token}"
    return RedirectResponse(url=redirect_url)


@router.get("/me")
async def auth_me(
    request: Request,
    user: Optional[UserInfo] = Depends(get_current_user)
):
    """
    현재 로그인한 사용자 정보 조회

    localhost 요청의 경우 자동으로 관리자로 처리됩니다.

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

    if user is None:
        return {"user": None}

    return {
        "user": {
            "email": user.email,
            "isAdmin": user.is_admin,
        }
    }


@router.post("/logout")
async def auth_logout():
    """
    로그아웃

    클라이언트 측에서 토큰을 삭제해야 합니다.
    서버 측에서는 별도의 처리가 필요하지 않습니다.
    """
    return {"message": "로그아웃되었습니다"}
