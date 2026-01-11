"""Activity Hub Sync Service - PUSH 방식 동기화."""

from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.models.activity import ActivityCenter, ActivityCourse
from app.core.config import settings, logger


class SyncService:
    """activity-hub로 데이터를 PUSH하는 서비스."""

    def __init__(self):
        """SyncService 초기화."""
        self.api_url = settings.ACTIVITY_HUB_PUSH_URL
        self.api_key = settings.ACTIVITY_HUB_SYNC_API_KEY
        print(f"[SyncService] INIT: api_url={self.api_url}, api_key={'SET' if self.api_key else 'NOT SET'}")
        logger.info(f"[SyncService] Initialized with api_url={self.api_url}, api_key={'SET' if self.api_key else 'NOT SET'}")

    def _map_category(self, category: Optional[str]) -> str:
        """카테고리 매핑."""
        if not category:
            return "sports"

        mapping = {
            "exercise": "sports",
            "swimming": "sports",
            "fitness": "sports",
            "yoga": "sports",
            "cooking": "cooking",
            "baking": "cooking",
            "art": "art",
            "craft": "art",
            "drawing": "art",
            "music": "music",
            "instrument": "music",
            "language": "language",
            "english": "language",
            "chinese": "language",
            "japanese": "language",
            "dance": "dance",
            "ballet": "dance",
        }
        return mapping.get(category.lower(), category)

    def _map_target_age(self, target_age: Optional[str]) -> str:
        """대상 연령 매핑."""
        if not target_age:
            return "all"

        mapping = {
            "infant": "infant",
            "toddler": "infant",
            "child": "child",
            "elementary": "child",
            "youth": "teen",
            "teen": "teen",
            "middle": "teen",
            "high": "teen",
            "adult": "adult",
            "senior": "senior",
            "elderly": "senior",
            "all": "all",
        }
        return mapping.get(target_age.lower(), "all")

    def _map_center_type(self, center_type: Optional[str]) -> str:
        """센터 타입 매핑."""
        if not center_type:
            return "public"

        mapping = {
            "public_city": "public",
            "public_district": "public",
            "public": "public",
            "department": "department",
            "dept": "department",
            "mart": "mart",
            "homeplus": "mart",
            "emart": "mart",
            "lottemart": "mart",
            "private": "private",
        }
        return mapping.get(center_type.lower(), "public")

    def _parse_days(self, day_of_week: Optional[str]) -> str:
        """요일 문자열을 JSON 배열로 변환."""
        if not day_of_week:
            return "[]"
        days = [d.strip() for d in day_of_week.split(",") if d.strip()]
        import json
        return json.dumps(days, ensure_ascii=False)

    def _format_time(self, time_start: Optional[str], time_end: Optional[str]) -> str:
        """시간 포맷 변환."""
        if not time_start:
            return ""
        if not time_end:
            return time_start
        return f"{time_start}-{time_end}"

    def _convert_center(self, center: ActivityCenter) -> dict:
        """ActivityCenter를 activity-hub 형식으로 변환."""
        # course_count 계산 (관계 조회)
        course_count = len(center.courses) if hasattr(center, "courses") else 0

        return {
            "source_id": center.id,
            "name": center.name,
            "address": center.address,
            "phone": center.phone,
            "website": center.website,
            "type": self._map_center_type(center.center_type),
            "region_sido": center.region_sido,
            "region_sigungu": center.region_sigungu,
            "lat": center.latitude,
            "lng": center.longitude,
            "course_count": course_count,
        }

    def _convert_course(self, course: ActivityCourse) -> dict:
        """ActivityCourse를 activity-hub 형식으로 변환."""
        # center_name 조회 (관계 조회)
        center_name = course.center.name if hasattr(course, "center") and course.center else None

        return {
            "source_id": course.source_id or str(course.id),
            "title": course.name,
            "center_id": course.center_id,
            "center_name": center_name,
            "category": self._map_category(course.category),
            "status": course.status or "active",
            "days": self._parse_days(course.day_of_week),
            "time": self._format_time(course.time_start, course.time_end),
            "registration_start": course.registration_start.isoformat() if course.registration_start else None,
            "registration_end": course.registration_end.isoformat() if course.registration_end else None,
            "course_start": course.course_start.isoformat() if course.course_start else None,
            "course_end": course.course_end.isoformat() if course.course_end else None,
            "price": course.fee,
            "target_age": self._map_target_age(course.target_age),
            "capacity": course.capacity,
            "current_enrollment": course.current_enrollment,
            "description": course.description,
            "instructor_name": course.instructor_name,
        }

    async def push_center_courses(self, db: Session, center_id: int) -> dict:
        """특정 센터의 강좌를 activity-hub로 PUSH.

        Args:
            db: DB 세션
            center_id: 센터 ID

        Returns:
            동기화 결과 딕셔너리
        """
        if not self.api_key:
            logger.error("[SyncService][PUSH] ACTIVITY_HUB_SYNC_API_KEY not set")
            return {"success": False, "error": "API key not set"}

        try:
            # 센터 및 강좌 조회
            center = db.query(ActivityCenter).filter(ActivityCenter.id == center_id).first()
            if not center:
                return {"success": False, "error": f"Center {center_id} not found"}

            courses = db.query(ActivityCourse).filter(ActivityCourse.center_id == center_id).all()

            logger.info(f"[SyncService][PUSH] Center {center_id} has {len(courses)} courses in DB")

            # 데이터 변환
            center_data = self._convert_center(center)
            courses_data = [self._convert_course(course) for course in courses]

            logger.info(f"[SyncService][PUSH] Sending {len(courses_data)} courses to activity-hub")

            # activity-hub로 전송
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "MonitorPage/1.0 (ActivityHub Sync Client)",
                "Content-Type": "application/json"
            }
            payload = {
                "centers": [center_data],
                "courses": courses_data,
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(self.api_url, json=payload, headers=headers)

                if response.status_code == 200:
                    result = response.json()
                    logger.info(
                        f"[SyncService][PUSH] Sync success: center_id={center_id}, "
                        f"centers={result.get('centersCount', 0)}, "
                        f"courses={result.get('coursesCount', 0)}"
                    )
                    return result
                else:
                    logger.error(
                        f"[SyncService][PUSH] Sync failed: {response.status_code}, "
                        f"response: {response.text}"
                    )
                    return {"success": False, "error": f"HTTP {response.status_code}"}

        except Exception as e:
            logger.error(f"[SyncService][PUSH] Sync error: {e}")
            return {"success": False, "error": str(e)}
