"""Activity Courses API Routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.activity.models.schemas import (
    CourseSearchParams,
    CourseResponse,
    CourseListResponse,
)
from app.modules.activity.services.course_service import CourseService

router = APIRouter(prefix="/courses", tags=["activity-courses"])


@router.get("", response_model=CourseListResponse)
def search_courses(
    region_sido: Optional[str] = Query(None, description="시/도"),
    region_sigungu: Optional[str] = Query(None, description="시/군/구"),
    category: Optional[str] = Query(None, description="카테고리"),
    target_age: Optional[str] = Query(None, description="대상 연령"),
    keyword: Optional[str] = Query(None, description="검색어"),
    day_of_week: Optional[str] = Query(None, description="요일"),
    fee_min: Optional[int] = Query(None, ge=0, description="최소 수강료"),
    fee_max: Optional[int] = Query(None, ge=0, description="최대 수강료"),
    registration_open: Optional[bool] = Query(None, description="접수 중인 강좌만"),
    center_id: Optional[int] = Query(None, description="센터 ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """강좌 검색."""
    service = CourseService(db)
    params = CourseSearchParams(
        region_sido=region_sido,
        region_sigungu=region_sigungu,
        category=category,
        target_age=target_age,
        keyword=keyword,
        day_of_week=day_of_week,
        fee_min=fee_min,
        fee_max=fee_max,
        registration_open=registration_open,
        center_id=center_id,
        page=page,
        page_size=page_size,
    )

    courses, total = service.search(params)

    return CourseListResponse(
        items=[service.to_response(c) for c in courses],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{course_id}", response_model=CourseResponse)
def get_course(
    course_id: int,
    db: Session = Depends(get_db),
):
    """강좌 상세 조회."""
    service = CourseService(db)
    course = service.get_by_id(course_id)

    if not course:
        raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")

    return service.to_response(course)


@router.get("/center/{center_id}", response_model=CourseListResponse)
def get_courses_by_center(
    center_id: int,
    status: Optional[str] = Query(None, description="상태 필터"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """센터별 강좌 목록 조회."""
    service = CourseService(db)
    courses, total = service.get_by_center(
        center_id=center_id,
        status=status,
        page=page,
        page_size=page_size,
    )

    return CourseListResponse(
        items=[service.to_response(c) for c in courses],
        total=total,
        page=page,
        page_size=page_size,
    )
