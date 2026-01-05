"""Center Service - 센터 관리 서비스."""

from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.activity import ActivityCenter, ActivityCourse
from app.modules.activity.models.schemas import (
    CenterCreate,
    CenterUpdate,
    CenterResponse,
)


class CenterService:
    """센터 관리 서비스."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, center_id: int) -> Optional[ActivityCenter]:
        """ID로 센터 조회."""
        return self.db.query(ActivityCenter).filter(
            ActivityCenter.id == center_id
        ).first()

    def get_list(
        self,
        region_sido: Optional[str] = None,
        region_sigungu: Optional[str] = None,
        center_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[ActivityCenter], int]:
        """센터 목록 조회."""
        query = self.db.query(ActivityCenter)

        # 필터링
        if region_sido:
            query = query.filter(ActivityCenter.region_sido == region_sido)
        if region_sigungu:
            query = query.filter(ActivityCenter.region_sigungu == region_sigungu)
        if center_type:
            query = query.filter(ActivityCenter.center_type == center_type)
        if is_active is not None:
            query = query.filter(ActivityCenter.is_active == is_active)
        if keyword:
            query = query.filter(
                ActivityCenter.name.contains(keyword) |
                ActivityCenter.operator.contains(keyword)
            )

        # 총 개수
        total = query.count()

        # 페이지네이션
        offset = (page - 1) * page_size
        centers = query.order_by(ActivityCenter.name).offset(offset).limit(page_size).all()

        return centers, total

    def create(self, data: CenterCreate) -> ActivityCenter:
        """센터 생성."""
        center = ActivityCenter(
            name=data.name,
            center_type=data.center_type,
            operator=data.operator,
            region_sido=data.region_sido,
            region_sigungu=data.region_sigungu,
            address=data.address,
            latitude=data.latitude,
            longitude=data.longitude,
            phone=data.phone,
            website=data.website,
            crawl_url=data.crawl_url,
            crawl_method=data.crawl_method or "static",
            crawl_config=data.crawl_config or {},
        )
        self.db.add(center)
        self.db.commit()
        self.db.refresh(center)
        return center

    def update(self, center_id: int, data: CenterUpdate) -> Optional[ActivityCenter]:
        """센터 수정."""
        center = self.get_by_id(center_id)
        if not center:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(center, key, value)

        center.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(center)
        return center

    def delete(self, center_id: int) -> bool:
        """센터 삭제."""
        center = self.get_by_id(center_id)
        if not center:
            return False

        self.db.delete(center)
        self.db.commit()
        return True

    def find_by_name_and_region(
        self,
        name: str,
        region_sido: Optional[str] = None,
        region_sigungu: Optional[str] = None,
    ) -> Optional[ActivityCenter]:
        """이름과 지역으로 센터 검색 (임포트용)."""
        query = self.db.query(ActivityCenter).filter(ActivityCenter.name == name)

        if region_sido:
            query = query.filter(ActivityCenter.region_sido == region_sido)
        if region_sigungu:
            query = query.filter(ActivityCenter.region_sigungu == region_sigungu)

        return query.first()

    def get_course_count(self, center_id: int) -> int:
        """센터의 강좌 수 조회."""
        return self.db.query(func.count(ActivityCourse.id)).filter(
            ActivityCourse.center_id == center_id
        ).scalar() or 0

    def update_last_crawled(self, center_id: int) -> None:
        """마지막 크롤링 시간 업데이트."""
        center = self.get_by_id(center_id)
        if center:
            center.last_crawled_at = datetime.now()
            self.db.commit()

    def to_response(self, center: ActivityCenter, include_count: bool = False) -> CenterResponse:
        """모델을 응답 스키마로 변환."""
        response_data = {
            "id": center.id,
            "name": center.name,
            "center_type": center.center_type,
            "operator": center.operator,
            "region_sido": center.region_sido,
            "region_sigungu": center.region_sigungu,
            "address": center.address,
            "latitude": center.latitude,
            "longitude": center.longitude,
            "phone": center.phone,
            "website": center.website,
            "crawl_url": center.crawl_url,
            "crawl_method": center.crawl_method,
            "crawl_config": center.crawl_config or {},
            "is_active": center.is_active,
            "created_at": center.created_at,
            "updated_at": center.updated_at,
            "last_crawled_at": center.last_crawled_at,
        }

        if include_count:
            response_data["course_count"] = self.get_course_count(center.id)

        return CenterResponse(**response_data)
