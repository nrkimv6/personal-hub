"""
알림 설정 API 엔드포인트

알림 설정 조회/업데이트 기능을 제공합니다.
"""

from fastapi import APIRouter, HTTPException
import json

from app.config import logger
from app.database import SessionLocal
from app.schemas.notification import NotificationSettings, NotificationSettingsUpdate
from sqlalchemy import text

router = APIRouter(
    prefix="/notification",
    tags=["notification"]
)


def get_notification_settings_from_db() -> NotificationSettings:
    """DB에서 알림 설정을 조회합니다."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT enable_telegram, enable_desktop, notify_states
            FROM notification_settings WHERE id = 1
        """)).fetchone()

        if result:
            notify_states = result[2]
            if isinstance(notify_states, str):
                try:
                    notify_states = json.loads(notify_states)
                except json.JSONDecodeError:
                    notify_states = ["available", "booking_success", "booking_failed", "error", "startup"]

            return NotificationSettings(
                enable_telegram=bool(result[0]),
                enable_desktop=bool(result[1]),
                notify_states=notify_states or []
            )

        # 기본값 반환
        return NotificationSettings(
            enable_telegram=True,
            enable_desktop=True,
            notify_states=["available", "booking_success", "booking_failed", "error", "startup"]
        )
    except Exception as e:
        logger.error(f"알림 설정 조회 중 오류: {str(e)}")
        return NotificationSettings(
            enable_telegram=True,
            enable_desktop=True,
            notify_states=["available", "booking_success", "booking_failed", "error", "startup"]
        )
    finally:
        db.close()


def update_notification_settings_in_db(settings: NotificationSettingsUpdate) -> NotificationSettings:
    """DB에서 알림 설정을 업데이트합니다."""
    db = SessionLocal()
    try:
        notify_states_json = json.dumps(settings.notify_states, ensure_ascii=False)

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
            notify_states=settings.notify_states
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
        - startup: 서버 시작
    """
    try:
        return update_notification_settings_in_db(settings)
    except Exception as e:
        logger.error(f"알림 설정 업데이트 중 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"알림 설정 업데이트 오류: {str(e)}")
