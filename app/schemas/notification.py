"""
Notification 스키마 (Pydantic)
알림 설정 관리 스키마
"""
from pydantic import BaseModel, Field
from typing import List


class NotificationSettings(BaseModel):
    """알림 설정 스키마"""
    enable_telegram: bool = Field(True, description="텔레그램 알림 활성화")
    enable_desktop: bool = Field(True, description="데스크톱 알림 활성화")
    notify_states: List[str] = Field(
        default_factory=lambda: ["available", "booking_success", "booking_failed", "error", "startup"],
        description="알림 받을 상태 목록"
    )


class NotificationSettingsUpdate(BaseModel):
    """알림 설정 업데이트 스키마"""
    enable_telegram: bool = Field(..., description="텔레그램 알림 활성화")
    enable_desktop: bool = Field(..., description="데스크톱 알림 활성화")
    notify_states: List[str] = Field(..., description="알림 받을 상태 목록")
