"""
인증 관련 유틸리티 및 FastAPI 의존성

Google OAuth를 통한 관리자 인증 시스템
- JWT 토큰 생성/검증
- 관리자 권한 확인 의존성
"""

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.core.config import settings


# HTTP Bearer 스키마 (Authorization: Bearer <token>)
security = HTTPBearer(auto_error=False)


class TokenData(BaseModel):
    """JWT 토큰에 저장되는 데이터"""
    email: str
    is_admin: bool = False
    exp: Optional[datetime] = None


class UserInfo(BaseModel):
    """현재 로그인한 사용자 정보"""
    email: str
    is_admin: bool


def create_access_token(email: str, is_admin: bool = False) -> str:
    """
    JWT 액세스 토큰 생성

    Args:
        email: 사용자 이메일
        is_admin: 관리자 여부

    Returns:
        JWT 토큰 문자열
    """
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    to_encode = {
        "sub": email,
        "is_admin": is_admin,
        "exp": expire
    }
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def verify_token(token: str) -> Optional[TokenData]:
    """
    JWT 토큰 검증

    Args:
        token: JWT 토큰 문자열

    Returns:
        TokenData 또는 None (유효하지 않은 경우)
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
        email: str = payload.get("sub")
        is_admin: bool = payload.get("is_admin", False)
        if email is None:
            return None
        return TokenData(email=email, is_admin=is_admin)
    except JWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[UserInfo]:
    """
    현재 로그인한 사용자 정보를 가져오는 의존성

    인증되지 않은 경우 None 반환 (에러 발생 안 함)
    공개 API에서 사용

    Returns:
        UserInfo 또는 None
    """
    if credentials is None:
        return None

    token_data = verify_token(credentials.credentials)
    if token_data is None:
        return None

    return UserInfo(email=token_data.email, is_admin=token_data.is_admin)


async def get_current_user_required(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> UserInfo:
    """
    현재 로그인한 사용자 정보를 가져오는 의존성 (필수)

    인증되지 않은 경우 401 에러 발생

    Returns:
        UserInfo

    Raises:
        HTTPException: 인증 실패 시 401
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = verify_token(credentials.credentials)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UserInfo(email=token_data.email, is_admin=token_data.is_admin)


async def require_admin(
    user: UserInfo = Depends(get_current_user_required)
) -> UserInfo:
    """
    관리자 권한이 필요한 API에서 사용하는 의존성

    관리자가 아닌 경우 403 에러 발생

    Returns:
        UserInfo (관리자인 경우)

    Raises:
        HTTPException: 관리자가 아닌 경우 403
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다"
        )
    return user


def is_admin_email(email: str) -> bool:
    """
    주어진 이메일이 관리자 이메일인지 확인

    Args:
        email: 확인할 이메일

    Returns:
        관리자 여부
    """
    if not settings.ADMIN_EMAIL:
        return False
    return email.lower() == settings.ADMIN_EMAIL.lower()
