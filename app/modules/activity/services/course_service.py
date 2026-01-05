"""Course Service - 강좌 관리 서비스."""

from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from app.models.activity import ActivityCenter, ActivityCourse
from app.modules.activity.models.schemas import (
    CourseSearchParams,
    CourseResponse,
)


class CourseService:
    """강좌 관리 서비스."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, course_id: int) -> Optional[ActivityCourse]:
        """ID로 강좌 조회."""
        return self.db.query(ActivityCourse).options(
            joinedload(ActivityCourse.center)
        ).filter(ActivityCourse.id == course_id).first()

    def get_by_source(
        self,
        center_id: int,
        source_id: str
    ) -> Optional[ActivityCourse]:
        """센터ID + source_id로 강좌 조회 (중복 체크용)."""
        return self.db.query(ActivityCourse).filter(
            ActivityCourse.center_id == center_id,
            ActivityCourse.source_id == source_id,
        ).first()

    def search(self, params: CourseSearchParams) -> Tuple[List[ActivityCourse], int]:
        """강좌 검색."""
        query = self.db.query(ActivityCourse).options(
            joinedload(ActivityCourse.center)
        )

        # 센터 기반 필터 (region)
        if params.region_sido or params.region_sigungu:
            query = query.join(ActivityCenter)
            if params.region_sido:
                query = query.filter(ActivityCenter.region_sido == params.region_sido)
            if params.region_sigungu:
                query = query.filter(ActivityCenter.region_sigungu == params.region_sigungu)

        # 센터 ID 필터
        if params.center_id:
            query = query.filter(ActivityCourse.center_id == params.center_id)

        # 카테고리 필터
        if params.category:
            query = query.filter(ActivityCourse.category == params.category)

        # 대상 연령 필터
        if params.target_age:
            query = query.filter(
                or_(
                    ActivityCourse.target_age == params.target_age,
                    ActivityCourse.target_age == "all"
                )
            )

        # 키워드 검색 (이름, 설명)
        if params.keyword:
            keyword_filter = f"%{params.keyword}%"
            query = query.filter(
                or_(
                    ActivityCourse.name.like(keyword_filter),
                    ActivityCourse.description.like(keyword_filter)
                )
            )

        # 요일 필터
        if params.day_of_week:
            query = query.filter(ActivityCourse.day_of_week.contains(params.day_of_week))

        # 수강료 필터
        if params.fee_min is not None:
            query = query.filter(
                or_(
                    ActivityCourse.fee >= params.fee_min,
                    ActivityCourse.fee.is_(None)
                )
            )
        if params.fee_max is not None:
            query = query.filter(
                or_(
                    ActivityCourse.fee <= params.fee_max,
                    ActivityCourse.fee.is_(None)
                )
            )

        # 접수 중인 강좌만
        if params.registration_open:
            now = datetime.now()
            query = query.filter(
                and_(
                    ActivityCourse.registration_start <= now,
                    ActivityCourse.registration_end >= now
                )
            )

        # 활성 상태만
        query = query.filter(ActivityCourse.status == "active")

        # 총 개수
        total = query.count()

        # 페이지네이션
        offset = (params.page - 1) * params.page_size
        courses = query.order_by(
            ActivityCourse.registration_start.desc().nullslast(),
            ActivityCourse.collected_at.desc()
        ).offset(offset).limit(params.page_size).all()

        return courses, total

    def get_by_center(
        self,
        center_id: int,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[ActivityCourse], int]:
        """센터별 강좌 목록 조회."""
        query = self.db.query(ActivityCourse).filter(
            ActivityCourse.center_id == center_id
        )

        if status:
            query = query.filter(ActivityCourse.status == status)

        total = query.count()

        offset = (page - 1) * page_size
        courses = query.order_by(
            ActivityCourse.course_start.asc().nullslast()
        ).offset(offset).limit(page_size).all()

        return courses, total

    def create(self, center_id: int, data: dict) -> ActivityCourse:
        """강좌 생성."""
        course = ActivityCourse(center_id=center_id, **data)
        self.db.add(course)
        self.db.commit()
        self.db.refresh(course)
        return course

    def update(self, course: ActivityCourse, data: dict) -> ActivityCourse:
        """강좌 수정."""
        for key, value in data.items():
            if hasattr(course, key):
                setattr(course, key, value)

        course.source_updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(course)
        return course

    def to_response(self, course: ActivityCourse) -> CourseResponse:
        """모델을 응답 스키마로 변환."""
        now = datetime.now()
        is_open = False
        if course.registration_start and course.registration_end:
            is_open = course.registration_start <= now <= course.registration_end

        return CourseResponse(
            id=course.id,
            center_id=course.center_id,
            source_id=course.source_id,
            source_url=course.source_url,
            name=course.name,
            description=course.description,
            category=course.category,
            subcategory=course.subcategory,
            target_age=course.target_age,
            level=course.level,
            capacity=course.capacity,
            fee=course.fee,
            material_fee=course.material_fee,
            fee_note=course.fee_note,
            registration_start=course.registration_start,
            registration_end=course.registration_end,
            course_start=course.course_start,
            course_end=course.course_end,
            day_of_week=course.day_of_week,
            time_start=course.time_start,
            time_end=course.time_end,
            total_sessions=course.total_sessions,
            instructor_name=course.instructor_name,
            instructor_bio=course.instructor_bio,
            status=course.status,
            current_enrollment=course.current_enrollment,
            collected_at=course.collected_at,
            source_updated_at=course.source_updated_at,
            center_name=course.center.name if course.center else None,
            is_registration_open=is_open,
        )
