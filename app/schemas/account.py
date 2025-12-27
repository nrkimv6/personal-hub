"""
Account 스키마 (Pydantic)
다중 프로필 지원을 위한 계정 관리 스키마
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.biz_item import BizItem


class BookingInfo(BaseModel):
    """예약 시 사용할 개인정보"""
    phone_last4: Optional[str] = Field(None, description="전화번호 뒷자리 4자리")
    visitor_name: Optional[str] = Field(None, description="실방문자 성함 (미입력 시 예매자 이름 사용)")
    is_member: Optional[str] = Field("네", description="가입 여부 (기본: 네)")
    has_visited: Optional[str] = Field("네", description="방문 여부 (기본: 네)")


class AccountBase(BaseModel):
    """Account 기본 스키마"""
    name: str = Field(..., description="계정명 (예: 메인계정, 서브계정1)")
    email: Optional[str] = Field(None, description="네이버 이메일 (선택)")
    profile_dir: str = Field(..., description="브라우저 프로필 디렉토리 이름")
    description: Optional[str] = Field(None, description="계정 설명")
    booking_info: Optional[BookingInfo] = Field(None, description="예약 시 사용할 개인정보")


class AccountCreate(AccountBase):
    """Account 생성 스키마"""
    is_active: bool = Field(True, description="활성화 여부")


class AccountUpdate(BaseModel):
    """Account 수정 스키마"""
    name: Optional[str] = Field(None, description="계정명")
    email: Optional[str] = Field(None, description="네이버 이메일")
    is_active: Optional[bool] = Field(None, description="활성화 여부")
    is_logged_in: Optional[bool] = Field(None, description="로그인 상태")
    description: Optional[str] = Field(None, description="계정 설명")
    booking_info: Optional[BookingInfo] = Field(None, description="예약 시 사용할 개인정보")


class Account(AccountBase):
    """Account 응답 스키마"""
    id: int
    is_active: bool
    is_logged_in: bool
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AccountWithItems(Account):
    """Account + 아이템 목록 응답 스키마"""
    biz_items: List["BizItem"] = []

    class Config:
        from_attributes = True


class AccountLoginStatus(BaseModel):
    """계정 로그인 상태 체크 응답"""
    service_account_id: int
    account_name: str
    is_logged_in: bool
    checked_at: datetime


# Forward reference 해결
from app.schemas.biz_item import BizItem
AccountWithItems.model_rebuild()
