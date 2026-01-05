"""Import Service - 외부 데이터 임포트 서비스."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.activity import ActivityCenter, ActivityCourse, ActivityCrawlRun
from app.modules.activity.models.schemas import (
    CourseImportItem,
    CourseImportRequest,
    CourseImportResponse,
    ImportErrorDetail,
)
from app.modules.activity.services.center_service import CenterService
from app.modules.activity.services.course_service import CourseService

logger = logging.getLogger(__name__)


class ImportService:
    """외부 데이터 임포트 서비스."""

    def __init__(self, db: Session):
        self.db = db
        self.center_service = CenterService(db)
        self.course_service = CourseService(db)
        # 센터 캐시 (임포트 중 동일 센터 반복 조회 방지)
        self._center_cache: dict[str, ActivityCenter] = {}

    def import_courses(
        self,
        request: CourseImportRequest,
        crawl_run_id: Optional[int] = None,
    ) -> CourseImportResponse:
        """
        강좌 데이터 임포트.

        1. 센터 매칭/생성
        2. 강좌 upsert
        3. 결과 반환
        """
        created = 0
        updated = 0
        skipped = 0
        errors: list[ImportErrorDetail] = []

        for idx, item in enumerate(request.courses):
            try:
                result = self._import_single_course(item, request.update_existing)
                if result == "created":
                    created += 1
                elif result == "updated":
                    updated += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error(f"Import error at index {idx}: {e}")
                errors.append(ImportErrorDetail(
                    index=idx,
                    source_id=item.source_id,
                    error=str(e)
                ))

        # crawl_run 업데이트
        if crawl_run_id:
            self._update_crawl_run(
                crawl_run_id,
                found=len(request.courses),
                new=created,
                updated=updated
            )

        self.db.commit()

        return CourseImportResponse(
            total=len(request.courses),
            created=created,
            updated=updated,
            skipped=skipped,
            errors=errors,
        )

    def _import_single_course(
        self,
        item: CourseImportItem,
        update_existing: bool,
    ) -> str:
        """
        단일 강좌 임포트.

        Returns:
            "created" | "updated" | "skipped"
        """
        # 1. 센터 매칭/생성
        center = self._get_or_create_center(item)

        # 2. 기존 강좌 확인
        existing = self.course_service.get_by_source(center.id, item.source_id)

        # 3. 강좌 데이터 준비
        course_data = self._prepare_course_data(item)

        if existing:
            if update_existing:
                self.course_service.update(existing, course_data)
                return "updated"
            else:
                return "skipped"
        else:
            self.course_service.create(center.id, course_data)
            return "created"

    def _get_or_create_center(self, item: CourseImportItem) -> ActivityCenter:
        """센터 매칭 또는 생성."""
        # 캐시 키 생성
        cache_key = f"{item.center_name}|{item.center_region_sido}|{item.center_region_sigungu}"

        if cache_key in self._center_cache:
            return self._center_cache[cache_key]

        # 기존 센터 검색
        center = self.center_service.find_by_name_and_region(
            name=item.center_name,
            region_sido=item.center_region_sido,
            region_sigungu=item.center_region_sigungu,
        )

        if not center:
            # 새 센터 생성
            center = ActivityCenter(
                name=item.center_name,
                center_type=item.center_type or "private",
                region_sido=item.center_region_sido,
                region_sigungu=item.center_region_sigungu,
                website=item.center_website,
            )
            self.db.add(center)
            self.db.flush()  # ID 생성

        self._center_cache[cache_key] = center
        return center

    def _prepare_course_data(self, item: CourseImportItem) -> dict:
        """CourseImportItem에서 강좌 데이터 추출."""
        return {
            "source_id": item.source_id,
            "source_url": item.source_url,
            "name": item.name,
            "description": item.description,
            "category": item.category,
            "subcategory": item.subcategory,
            "target_age": item.target_age,
            "level": item.level,
            "capacity": item.capacity,
            "fee": item.fee,
            "material_fee": item.material_fee,
            "fee_note": item.fee_note,
            "registration_start": item.registration_start,
            "registration_end": item.registration_end,
            "course_start": item.course_start,
            "course_end": item.course_end,
            "day_of_week": item.day_of_week,
            "time_start": item.time_start,
            "time_end": item.time_end,
            "total_sessions": item.total_sessions,
            "instructor_name": item.instructor_name,
            "instructor_bio": item.instructor_bio,
        }

    def _update_crawl_run(
        self,
        run_id: int,
        found: int,
        new: int,
        updated: int
    ) -> None:
        """크롤링 실행 기록 업데이트."""
        run = self.db.query(ActivityCrawlRun).filter(
            ActivityCrawlRun.id == run_id
        ).first()

        if run:
            run.mark_completed(found=found, new=new, updated=updated)

    def create_crawl_run(self, center_id: Optional[int] = None) -> ActivityCrawlRun:
        """크롤링 실행 기록 생성."""
        run = ActivityCrawlRun(center_id=center_id)
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def fail_crawl_run(self, run_id: int, error: str) -> None:
        """크롤링 실행 실패 처리."""
        run = self.db.query(ActivityCrawlRun).filter(
            ActivityCrawlRun.id == run_id
        ).first()

        if run:
            run.mark_failed(error)
            self.db.commit()
