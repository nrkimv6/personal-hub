"""
ServiceAccount 스키마 (Pydantic)
서비스별 계정 관리 스키마
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any


class BookingInfo(BaseModel):
    """예약 시 사용할 개인정보 (네이버 예약 전용)"""
    phone_last4: Optional[str] = Field(None, description="전화번호 뒷자리 4자리")
    visitor_name: Optional[str] = Field(None, description="실방문자 성함 (미입력 시 예매자 이름 사용)")
    is_member: Optional[str] = Field("네", description="가입 여부 (기본: 네)")
    has_visited: Optional[str] = Field("네", description="방문 여부 (기본: 네)")


class ServiceAccountBase(BaseModel):
    """ServiceAccount 기본 스키마"""
    service_type: str = Field(..., description="서비스 타입 (naver, instagram, coupang)")
    identifier: Optional[str] = Field(None, description="이메일 또는 username")
    is_logged_in: bool = Field(False, description="로그인 상태")
    credentials: Optional[Dict[str, Any]] = Field(None, description="서비스별 추가 정보 (JSON)")


class ServiceAccountCreate(BaseModel):
    """ServiceAccount 생성 스키마"""
    service_type: str = Field(..., description="서비스 타입 (naver, instagram, coupang)")
    identifier: Optional[str] = Field(None, description="이메일 또는 username")
    password: Optional[str] = Field(None, description="비밀번호 (암호화 저장)")
    credentials: Optional[Dict[str, Any]] = Field(None, description="서비스별 추가 정보")


class ServiceAccountUpdate(BaseModel):
    """ServiceAccount 수정 스키마"""
    identifier: Optional[str] = Field(None, description="이메일 또는 username")
    password: Optional[str] = Field(None, description="비밀번호 (암호화 저장)")
    is_logged_in: Optional[bool] = Field(None, description="로그인 상태")
    credentials: Optional[Dict[str, Any]] = Field(None, description="서비스별 추가 정보")


class ServiceAccountResponse(ServiceAccountBase):
    """ServiceAccount 응답 스키마"""
    id: int
    profile_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ServiceAccountWithProfile(ServiceAccountResponse):
    """ServiceAccount + 프로필 정보 응답 스키마"""
    profile_name: Optional[str] = None
    profile_dir: Optional[str] = None

    class Config:
        from_attributes = True


class ServiceAccountLoginStatus(BaseModel):
    """서비스 계정 로그인 상태 체크 응답"""
    service_account_id: int
    profile_id: int
    profile_name: str
    service_type: str
    identifier: Optional[str]
    is_logged_in: bool
    checked_at: datetime


# 네이버 계정 전용 스키마 (booking_info 포함)
class NaverAccountCreate(ServiceAccountCreate):
    """네이버 계정 생성 스키마"""
    service_type: str = Field("naver", description="서비스 타입")
    booking_info: Optional[BookingInfo] = Field(None, description="예약 시 사용할 개인정보")


class NaverAccountUpdate(ServiceAccountUpdate):
    """네이버 계정 수정 스키마"""
    booking_info: Optional[BookingInfo] = Field(None, description="예약 시 사용할 개인정보")
