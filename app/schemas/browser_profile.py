"""
BrowserProfile 스키마 (Pydantic)
브라우저 프로필 관리 스키마
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


class BrowserProfileBase(BaseModel):
    """BrowserProfile 기본 스키마"""
    name: str = Field(..., description="프로필명 (예: 메인, 서브1)")
    profile_dir: str = Field(..., description="브라우저 프로필 디렉토리 이름")
    description: Optional[str] = Field(None, description="프로필 설명")


class BrowserProfileCreate(BrowserProfileBase):
    """BrowserProfile 생성 스키마"""
    is_active: bool = Field(True, description="활성화 여부")


class BrowserProfileUpdate(BaseModel):
    """BrowserProfile 수정 스키마"""
    name: Optional[str] = Field(None, description="프로필명")
    description: Optional[str] = Field(None, description="프로필 설명")
    is_active: Optional[bool] = Field(None, description="활성화 여부")


class BrowserProfile(BrowserProfileBase):
    """BrowserProfile 응답 스키마"""
    id: int
    is_active: bool
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BrowserProfileWithAccounts(BrowserProfile):
    """BrowserProfile + 서비스 계정 목록 응답 스키마"""
    service_accounts: List["ServiceAccountResponse"] = []

    class Config:
        from_attributes = True


# Forward reference 해결을 위한 import
from app.schemas.service_account import ServiceAccountResponse
BrowserProfileWithAccounts.model_rebuild()
