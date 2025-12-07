"""
스케줄 기반 모니터링 서비스

계층형 데이터 구조(businesses -> biz_items -> monitor_schedules)를 사용하여
모니터링 스케줄을 관리합니다.

이 서비스는 browser_service.py에서 사용되며,
기존 monitoring_system_manager.py의 역할을 대체합니다.
"""
import json
from datetime import datetime, date
from typing import Dict, Any, Optional, List
from sqlalchemy import text

from app.database import SessionLocal
from app.config import settings, logger
from app.utils.url_builder import build_naver_booking_url
from app.services.schedule_service import calculate_default_interval


class ScheduleMonitorService:
    """스케줄 기반 모니터링 서비스"""

    def __init__(self):
        """서비스 초기화"""
        pass

    def get_schedule(self, schedule_id: int) -> Optional[Dict[str, Any]]:
        """
        스케줄 정보를 조회합니다.

        Args:
            schedule_id: 스케줄 ID

        Returns:
            스케줄 정보 딕셔너리 또는 None
        """
        db = SessionLocal()
        try:
            result = db.execute(text("""
                SELECT
                    ms.id as schedule_id,
                    ms.date,
                    ms.times,
                    ms.is_enabled,
                    ms.is_active,
                    ms.run_status,
                    ms.interval,
                    ms.custom_interval,
                    ms.error_count,
                    ms.last_error,
                    ms.booking_count,
                    ms.last_booking_time,
                    bi.id as biz_item_id,
                    bi.biz_item_id as naver_biz_item_id,
                    bi.name as item_name,
                    COALESCE(ms.time_range, bi.time_range) as time_range,
                    COALESCE(ms.auto_booking_enabled, bi.auto_booking_enabled) as auto_booking_enabled,
                    bi.max_bookings_per_schedule,
                    COALESCE(ms.account_id, bi.account_id) as account_id,
                    b.id as business_id,
                    b.business_id as naver_business_id,
                    b.business_type_id,
                    b.name as business_name,
                    b.category,
                    b.service_type,
                    b.booking_options
                FROM monitor_schedules ms
                JOIN biz_items bi ON ms.biz_item_id = bi.id
                JOIN businesses b ON bi.business_id = b.id
                WHERE ms.id = :schedule_id
            """), {"schedule_id": schedule_id}).fetchone()

            if not result:
                return None

            # URL 생성
            url = build_naver_booking_url(
                business_type_id=result[21],
                business_id=result[20],
                biz_item_id=result[13],
                date=result[1]
            )

            # interval 계산: custom_interval이면 저장된 값, 아니면 날짜 기반 기본값
            custom_interval = bool(result[7])
            if custom_interval and result[6] is not None:
                effective_interval = result[6]
            else:
                effective_interval = calculate_default_interval(result[1])

            return {
                "id": result[0],
                "date": result[1],
                "times": json.loads(result[2]) if result[2] else [],
                "is_enabled": bool(result[3]),
                "is_active": bool(result[4]),
                "run_status": result[5],
                "interval": effective_interval,
                "custom_interval": custom_interval,
                "error_count": result[8] or 0,
                "last_error": result[9],
                "booking_count": result[10] or 0,
                "last_booking_time": result[11],
                "biz_item_id": result[12],
                "naver_biz_item_id": result[13],
                "item_name": result[14],
                "time_range": result[15],
                "auto_booking_enabled": bool(result[16]),
                "max_bookings_per_schedule": result[17] or 1,
                "account_id": result[18],  # 다중 프로필 지원
                "business_id": result[19],
                "naver_business_id": result[20],
                "business_type_id": result[21],
                "business_name": result[22],
                "category": result[23],
                "service_type": result[24],
                "booking_options": json.loads(result[25]) if result[25] else None,
                "url": url,
                "label": f"{result[22]} - {result[14]} ({result[1]})"
            }

        except Exception as e:
            logger.error(f"스케줄 조회 실패 (ID: {schedule_id}): {str(e)}")
            return None
        finally:
            db.close()

    def update_schedule(self, schedule_id: int, update_data: Dict[str, Any]) -> bool:
        """
        스케줄 정보를 업데이트합니다.

        Args:
            schedule_id: 스케줄 ID
            update_data: 업데이트할 데이터 딕셔너리

        Returns:
            성공 여부
        """
        db = SessionLocal()
        try:
            # 동적으로 UPDATE 쿼리 생성
            set_clauses = []
            params = {"schedule_id": schedule_id}

            field_mapping = {
                "is_enabled": "is_enabled",
                "is_active": "is_active",
                "run_status": "run_status",
                "interval": "interval",
                "custom_interval": "custom_interval",
                "error_count": "error_count",
                "last_error": "last_error",
                "booking_count": "booking_count",
                "last_booking_time": "last_booking_time",
                "times": "times",
                "last_check_time": "last_check_time",
                "next_run_time": "next_run_time",
            }

            for key, value in update_data.items():
                if key in field_mapping:
                    db_field = field_mapping[key]
                    set_clauses.append(f"{db_field} = :{key}")

                    # times는 JSON으로 저장
                    if key == "times" and isinstance(value, list):
                        params[key] = json.dumps(value)
                    else:
                        params[key] = value

            if not set_clauses:
                return True  # 업데이트할 것이 없음

            # updated_at 추가
            set_clauses.append("updated_at = :updated_at")
            params["updated_at"] = datetime.now().isoformat()

            query = f"UPDATE monitor_schedules SET {', '.join(set_clauses)} WHERE id = :schedule_id"
            result = db.execute(text(query), params)
            db.commit()

            return result.rowcount > 0

        except Exception as e:
            db.rollback()
            logger.error(f"스케줄 업데이트 실패 (ID: {schedule_id}): {str(e)}")
            return False
        finally:
            db.close()

    def increment_error_count(self, schedule_id: int, error_message: str) -> bool:
        """
        에러 카운트를 증가시키고 에러 메시지를 저장합니다.

        Args:
            schedule_id: 스케줄 ID
            error_message: 에러 메시지

        Returns:
            성공 여부
        """
        db = SessionLocal()
        try:
            db.execute(text("""
                UPDATE monitor_schedules
                SET error_count = error_count + 1,
                    last_error = :error_message,
                    updated_at = :updated_at
                WHERE id = :schedule_id
            """), {
                "schedule_id": schedule_id,
                "error_message": error_message[:500] if error_message else None,  # 길이 제한
                "updated_at": datetime.now().isoformat()
            })
            db.commit()
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"에러 카운트 증가 실패 (ID: {schedule_id}): {str(e)}")
            return False
        finally:
            db.close()

    def reset_error_count(self, schedule_id: int) -> bool:
        """
        에러 카운트를 초기화합니다.

        Args:
            schedule_id: 스케줄 ID

        Returns:
            성공 여부
        """
        return self.update_schedule(schedule_id, {
            "error_count": 0,
            "last_error": None
        })

    def increment_booking_count(self, schedule_id: int) -> bool:
        """
        예약 카운트를 증가시킵니다.

        Args:
            schedule_id: 스케줄 ID

        Returns:
            성공 여부
        """
        db = SessionLocal()
        try:
            db.execute(text("""
                UPDATE monitor_schedules
                SET booking_count = booking_count + 1,
                    last_booking_time = :booking_time,
                    updated_at = :updated_at
                WHERE id = :schedule_id
            """), {
                "schedule_id": schedule_id,
                "booking_time": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            })
            db.commit()
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"예약 카운트 증가 실패 (ID: {schedule_id}): {str(e)}")
            return False
        finally:
            db.close()

    def set_run_status(self, schedule_id: int, status: str, error: str = None) -> bool:
        """
        실행 상태를 설정합니다.

        Args:
            schedule_id: 스케줄 ID
            status: 상태 (idle, pending, queued, running, paused, stopped, error)
            error: 에러 메시지 (선택)

        Returns:
            성공 여부
        """
        update_data = {"run_status": status}
        if error:
            update_data["last_error"] = error
        return self.update_schedule(schedule_id, update_data)

    def set_active(self, schedule_id: int, is_active: bool) -> bool:
        """
        활성 상태를 설정합니다.

        Args:
            schedule_id: 스케줄 ID
            is_active: 활성 상태

        Returns:
            성공 여부
        """
        return self.update_schedule(schedule_id, {"is_active": is_active})

    def get_active_schedules(self) -> List[Dict[str, Any]]:
        """
        활성화된 모든 스케줄을 조회합니다. (is_enabled=True)

        Returns:
            스케줄 정보 딕셔너리 리스트
        """
        db = SessionLocal()
        try:
            result = db.execute(text("""
                SELECT ms.id
                FROM monitor_schedules ms
                WHERE ms.is_enabled = 1
                ORDER BY ms.id DESC
            """)).fetchall()

            schedules = []
            for row in result:
                schedule = self.get_schedule(row[0])
                if schedule:
                    schedules.append(schedule)

            return schedules

        except Exception as e:
            logger.error(f"활성 스케줄 조회 실패: {str(e)}")
            return []
        finally:
            db.close()

    def can_book(self, schedule_id: int) -> bool:
        """
        예약 가능 여부를 확인합니다.
        (max_bookings_per_schedule 체크)

        Args:
            schedule_id: 스케줄 ID

        Returns:
            예약 가능 여부
        """
        schedule = self.get_schedule(schedule_id)
        if not schedule:
            return False

        max_bookings = schedule.get("max_bookings_per_schedule", 1)
        current_count = schedule.get("booking_count", 0)

        return current_count < max_bookings


# 전역 인스턴스 (싱글톤 패턴)
_schedule_monitor_service = None


def get_schedule_monitor_service() -> ScheduleMonitorService:
    """ScheduleMonitorService 싱글톤 인스턴스를 반환합니다."""
    global _schedule_monitor_service
    if _schedule_monitor_service is None:
        _schedule_monitor_service = ScheduleMonitorService()
    return _schedule_monitor_service
