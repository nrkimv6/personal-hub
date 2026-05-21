"""
알림 설정 API 엔드포인트

알림 설정 조회/업데이트 기능을 제공합니다.
"""

from fastapi import APIRouter, HTTPException
import json

from app.config import logger
from app.database import SessionLocal
from app.schemas.notification import (
    AlertRuleOverrideResponse,
    AlertRuleOverrideUpdate,
    AlertRuleSettingsResponse,
    NotificationSettings,
    NotificationSettingsUpdate,
)
from app.services.alert_rule_settings_service import (
    get_effective_alert_rules,
    update_alert_rule_override,
)
from sqlalchemy import text

router = APIRouter(
    prefix="/notification",
    tags=["notification"]
)

_DEFAULT_NOTIFY_STATES = [
    "available",
    "booking_success",
    "booking_failed",
    "error",
    "popup_new",
]

_ALLOWED_NOTIFY_STATES = {*_DEFAULT_NOTIFY_STATES, "failure_warning"}


def _normalize_notify_states(states: list[str] | None) -> list[str]:
    """알림 상태 목록에서 지원하지 않는 항목을 제거합니다."""
    if not states:
        return []
    return [state for state in states if state in _ALLOWED_NOTIFY_STATES]


def get_notification_settings_from_db() -> NotificationSettings:
    """DB에서 알림 설정을 조회합니다."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT enable_telegram, enable_desktop, notify_states
            FROM notification_settings WHERE id = 1
        """)).mappings().first()

        if result:
            notify_states = result["notify_states"]
            if isinstance(notify_states, str):
                try:
                    notify_states = json.loads(notify_states)
                except json.JSONDecodeError:
                    notify_states = _DEFAULT_NOTIFY_STATES.copy()
            notify_states = _normalize_notify_states(notify_states)

            return NotificationSettings(
                enable_telegram=bool(result["enable_telegram"]),
                enable_desktop=bool(result["enable_desktop"]),
                notify_states=notify_states or []
            )

        # 기본값 반환
        return NotificationSettings(
            enable_telegram=True,
            enable_desktop=True,
            notify_states=_DEFAULT_NOTIFY_STATES.copy()
        )
    except Exception as e:
        logger.error(f"알림 설정 조회 중 오류: {str(e)}")
        return NotificationSettings(
            enable_telegram=True,
            enable_desktop=True,
            notify_states=_DEFAULT_NOTIFY_STATES.copy()
        )
    finally:
        db.close()


def update_notification_settings_in_db(settings: NotificationSettingsUpdate) -> NotificationSettings:
    """DB에서 알림 설정을 업데이트합니다."""
    db = SessionLocal()
    try:
        notify_states = _normalize_notify_states(settings.notify_states)
        notify_states_json = json.dumps(notify_states, ensure_ascii=False)

        # 기존 설정 확인 또는 생성
        result = db.execute(text("SELECT id FROM notification_settings WHERE id = 1")).fetchone()

        if not result:
            db.execute(text("""
                INSERT INTO notification_settings (id, enable_telegram, enable_desktop, notify_states)
                VALUES (1, :enable_telegram, :enable_desktop, :notify_states)
            """), {
                "enable_telegram": settings.enable_telegram,
                "enable_desktop": settings.enable_desktop,
                "notify_states": notify_states_json
            })
        else:
            db.execute(text("""
                UPDATE notification_settings
                SET enable_telegram = :enable_telegram,
                    enable_desktop = :enable_desktop,
                    notify_states = :notify_states,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
            """), {
                "enable_telegram": settings.enable_telegram,
                "enable_desktop": settings.enable_desktop,
                "notify_states": notify_states_json
            })

        db.commit()

        return NotificationSettings(
            enable_telegram=settings.enable_telegram,
            enable_desktop=settings.enable_desktop,
            notify_states=notify_states
        )
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


@router.get("/settings", response_model=NotificationSettings)
async def get_notification_settings():
    """
    현재 알림 설정을 조회합니다.
    """
    return get_notification_settings_from_db()


@router.put("/settings", response_model=NotificationSettings)
async def update_notification_settings(settings: NotificationSettingsUpdate):
    """
    알림 설정을 업데이트합니다.

    - enable_telegram: 텔레그램 알림 활성화 여부
    - enable_desktop: 데스크톱 알림 활성화 여부
    - notify_states: 알림 받을 상태 목록
        - available: 예약 가능 발견
        - booking_success: 예약 성공
        - booking_failed: 예약 실패
        - error: 오류 발생
        - popup_new: 팝업 URL 모니터 신규 항목 감지
    """
    try:
        return update_notification_settings_in_db(settings)
    except Exception as e:
        logger.error(f"알림 설정 업데이트 중 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"알림 설정 업데이트 오류: {str(e)}")


@router.get("/alert-rules", response_model=list[AlertRuleSettingsResponse])
async def get_alert_rules():
    """
    실패 알림 rule별 effective 설정을 조회합니다.

    Registry에 없는 stale override는 stale=true로 표시하며 자동 삭제하지 않습니다.
    """
    db = SessionLocal()
    try:
        return get_effective_alert_rules(db)
    except Exception as e:
        logger.error(f"알림 rule 설정 조회 중 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail={"code": "ALERT_RULE_SETTINGS_READ_FAILED", "message": str(e)})
    finally:
        db.close()


@router.put("/alert-rules/{rule_id}", response_model=AlertRuleOverrideResponse)
async def update_alert_rule(rule_id: str, payload: AlertRuleOverrideUpdate):
    """
    실패 알림 rule override를 저장합니다.
    """
    db = SessionLocal()
    try:
        rule = update_alert_rule_override(db, rule_id, payload)
        return AlertRuleOverrideResponse(rule=rule)
    except ValueError as e:
        code = str(e)
        status_code = 409 if code == "ALERT_RULE_STALE_WRITE" else 400
        raise HTTPException(status_code=status_code, detail={"code": code})
    except Exception as e:
        db.rollback()
        logger.error(f"알림 rule 설정 업데이트 중 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail={"code": "ALERT_RULE_SETTINGS_UPDATE_FAILED", "message": str(e)})
    finally:
        db.close()
