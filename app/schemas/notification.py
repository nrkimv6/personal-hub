"""
Notification 스키마 (Pydantic)
알림 설정 관리 스키마
"""
from pydantic import BaseModel, Field
from typing import List, Literal


class NotificationSettings(BaseModel):
    """알림 설정 스키마"""
    enable_telegram: bool = Field(True, description="텔레그램 알림 활성화")
    enable_desktop: bool = Field(True, description="데스크톱 알림 활성화")
    notify_states: List[str] = Field(
        default_factory=lambda: [
            "available",
            "booking_success",
            "booking_failed",
            "error",
            "popup_new",
        ],
        description="알림 받을 상태 목록"
    )


class NotificationSettingsUpdate(BaseModel):
    """알림 설정 업데이트 스키마"""
    enable_telegram: bool = Field(..., description="텔레그램 알림 활성화")
    enable_desktop: bool = Field(..., description="데스크톱 알림 활성화")
    notify_states: List[str] = Field(..., description="알림 받을 상태 목록")


AlertRuleSeverity = Literal["critical", "warning", "record_only"]
AlertRuleChannel = Literal["telegram", "desktop", "ui_only"]


class AlertRuleSettingsResponse(BaseModel):
    """Effective alert rule settings read model."""
    rule_id: str
    source: str
    enabled: bool
    default_severity: AlertRuleSeverity
    effective_severity: AlertRuleSeverity
    default_channel: AlertRuleChannel = "telegram"
    effective_channel: AlertRuleChannel = "telegram"
    severity_override: AlertRuleSeverity | None = None
    channel_override: AlertRuleChannel | None = None
    cooldown_seconds: int
    burst_threshold: int | None = None
    locked: bool
    stale: bool = False
    has_override: bool = False
    version: int | None = None
    updated_at: str | None = None


class AlertRuleOverrideUpdate(BaseModel):
    """Alert rule user override update schema."""
    enabled: bool | None = None
    severity_override: AlertRuleSeverity | None = None
    channel_override: AlertRuleChannel | None = None
    cooldown_seconds: int | None = Field(None, ge=0)
    burst_threshold: int | None = Field(None, ge=1)
    expected_version: int | None = None
    expected_updated_at: str | None = None


class AlertRuleOverrideResponse(BaseModel):
    """Alert rule override write response."""
    rule: AlertRuleSettingsResponse
