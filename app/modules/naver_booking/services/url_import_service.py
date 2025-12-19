"""
URL Import Service - 통합 URL 임포트 서비스

네이버 예약 URL에서 업체/상품/스케줄 정보를 조회하고 DB에 저장합니다.
Snipe와 BizItem에서 공통으로 사용됩니다.

작성일: 2025-12-03
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy.orm import Session

from app.config import logger
from app.modules.naver_booking.utils.parsers import parse_naver_booking_url, ParsedNaverUrl
from app.modules.naver_booking.services.graphql_client import (
    get_naver_graphql_client,
    BusinessInfo,
    BizItemInfo,
    ScheduleInfo,
    ScheduleSlot,
)
from app.modules.naver_booking.services.business_service import business_service
from app.modules.naver_booking.services.biz_item_service import biz_item_service


@dataclass
class UrlImportResult:
    """URL 임포트 결과"""
    success: bool
    message: str

    # 파싱 정보
    parsed_url: Optional[ParsedNaverUrl] = None

    # DB 레코드 ID
    business_db_id: Optional[int] = None
    biz_item_db_id: Optional[int] = None

    # 조회된 상세 정보
    business_info: Optional[BusinessInfo] = None
    biz_item_info: Optional[BizItemInfo] = None
    schedule_info: Optional[ScheduleInfo] = None

    # 스마트 시간 추천
    recommended_date: Optional[str] = None
    recommended_times: List[str] = field(default_factory=list)
    all_available_dates: List[str] = field(default_factory=list)
    all_available_times: List[str] = field(default_factory=list)
    is_weekend: bool = False

    # 가격 정보
    prices: List[Dict[str, Any]] = field(default_factory=list)

    # 예약 설정
    min_booking_count: Optional[int] = None
    max_booking_count: Optional[int] = None


class UrlImportService:
    """URL 기반 통합 임포트 서비스"""

    async def import_from_url(
        self,
        db: Session,
        url: str,
        target_date: Optional[str] = None,
        prefer_time_start: Optional[str] = None,
        prefer_time_end: Optional[str] = None,
        fetch_schedule: bool = True,
        save_to_db: bool = True
    ) -> UrlImportResult:
        """
        URL에서 정보를 추출하고 DB에 저장합니다.

        Args:
            db: 데이터베이스 세션
            url: 네이버 예약 URL
            target_date: 원하는 예약 날짜 (없으면 첫 가능일 또는 URL의 날짜)
            prefer_time_start: 선호 시작 시간 (예: "18:00")
            prefer_time_end: 선호 종료 시간 (예: "21:00")
            fetch_schedule: 스케줄(예약 가능 시간) 조회 여부
            save_to_db: DB 저장 여부

        Returns:
            UrlImportResult: 임포트 결과
        """
        # 1. URL 파싱
        parsed = parse_naver_booking_url(url)
        if not parsed.is_valid:
            return UrlImportResult(
                success=False,
                message=f"URL 파싱 실패: {parsed.error}",
                parsed_url=parsed
            )

        logger.info(f"[UrlImport] URL 파싱 성공: business={parsed.business_id}, item={parsed.item_id}")

        # 2. GraphQL API로 정보 조회
        client = get_naver_graphql_client()

        business_info: Optional[BusinessInfo] = None
        biz_item_info: Optional[BizItemInfo] = None
        schedule_info: Optional[ScheduleInfo] = None

        try:
            # Business + BizItem 정보 조회
            result = await client.fetch_all_info(parsed.business_id, parsed.item_id)
            business_info = result.get("business")
            biz_item_info = result.get("item")

            if business_info:
                logger.info(f"[UrlImport] Business 조회: {business_info.name}")
            if biz_item_info:
                logger.info(f"[UrlImport] BizItem 조회: {biz_item_info.name}")

        except Exception as e:
            logger.warning(f"[UrlImport] Business/BizItem API 조회 실패: {e}")

        # 3. Schedule (예약 가능 시간) 조회
        if fetch_schedule and parsed.business_type_id:
            try:
                schedule_info = await client.fetch_schedule(
                    business_type_id=int(parsed.business_type_id),
                    business_id=parsed.business_id,
                    biz_item_id=parsed.item_id,
                    start_date=parsed.start_date  # URL에 날짜 있으면 그 날짜부터
                )
                if schedule_info:
                    logger.info(f"[UrlImport] Schedule 조회: {len(schedule_info.available_dates)}개 날짜")
            except Exception as e:
                logger.warning(f"[UrlImport] Schedule API 조회 실패: {e}")

        # 4. DB 저장
        business_db_id = None
        biz_item_db_id = None

        if save_to_db:
            try:
                # Business 저장
                business = business_service.get_or_create(
                    db=db,
                    business_id=parsed.business_id,
                    business_type_id=business_info.business_type_id if business_info else (int(parsed.business_type_id) if parsed.business_type_id else None),
                    name=business_info.name if business_info else f"Business_{parsed.business_id}",
                    service_type="naver",
                    category=parsed.category,
                )
                business_db_id = business.id

                # Business 상세정보 업데이트 (API에서 가져온 경우)
                if business_info and not business.api_synced_at:
                    from app.schemas.business import BusinessUpdate
                    update_data = BusinessUpdate(
                        name=business_info.name,
                        service_name=business_info.service_name,
                        road_address=business_info.road_address,
                        jibun_address=business_info.jibun_address,
                        detail_address=business_info.detail_address,
                        latitude=business_info.latitude,
                        longitude=business_info.longitude,
                        phone=business_info.phone,
                    )
                    business_service.update(db, business.id, update_data)
                    business_service.mark_api_synced(db, business.id)

                logger.info(f"[UrlImport] Business 저장: id={business_db_id}")

                # BizItem 저장
                biz_item = biz_item_service.get_or_create(
                    db=db,
                    business_id=business_db_id,
                    biz_item_id=parsed.item_id,
                    name=biz_item_info.name if biz_item_info else f"Item_{parsed.item_id}",
                )
                biz_item_db_id = biz_item.id

                # BizItem 상세정보 업데이트
                if biz_item_info and not biz_item.api_synced_at:
                    from app.schemas.biz_item import BizItemUpdate
                    update_data = BizItemUpdate(
                        name=biz_item_info.name,
                        description=biz_item_info.description,
                        biz_item_type=biz_item_info.biz_item_type,
                        biz_item_sub_type=biz_item_info.biz_item_sub_type,
                        booking_count_type=biz_item_info.booking_count_type,
                        min_booking_count=biz_item_info.min_booking_count,
                        max_booking_count=biz_item_info.max_booking_count,
                        start_date=biz_item_info.start_date,
                        end_date=biz_item_info.end_date,
                    )
                    biz_item_service.update(db, biz_item.id, update_data)
                    biz_item_service.mark_api_synced(db, biz_item.id)

                logger.info(f"[UrlImport] BizItem 저장: id={biz_item_db_id}")

            except Exception as e:
                logger.error(f"[UrlImport] DB 저장 실패: {e}")

        # 5. 스마트 시간 추천
        recommended_date = target_date or parsed.start_date
        recommended_times = []
        all_available_dates = []
        all_available_times = []
        is_weekend = False
        prices = []
        min_booking_count = None
        max_booking_count = None

        if schedule_info:
            all_available_dates = schedule_info.available_dates

            # 스마트 시간 선택
            smart_result = client.get_smart_time_slots(
                schedule_info=schedule_info,
                target_date=recommended_date,
                prefer_time_start=prefer_time_start,
                prefer_time_end=prefer_time_end
            )

            recommended_date = smart_result.get("target_date")
            recommended_times = smart_result.get("recommended_times", [])
            all_available_times = smart_result.get("all_available_times", [])
            is_weekend = smart_result.get("is_weekend", False)

            # 첫 슬롯에서 가격 및 예약 인원 정보 추출
            if recommended_date and recommended_date in schedule_info.slots_by_date:
                first_slot = schedule_info.slots_by_date[recommended_date][0]
                prices = first_slot.prices
                min_booking_count = first_slot.min_booking_count
                max_booking_count = first_slot.max_booking_count

        # BizItem에서 예약 인원 정보 보완
        if biz_item_info:
            if min_booking_count is None:
                min_booking_count = biz_item_info.min_booking_count
            if max_booking_count is None:
                max_booking_count = biz_item_info.max_booking_count

        return UrlImportResult(
            success=True,
            message="URL 임포트 성공",
            parsed_url=parsed,
            business_db_id=business_db_id,
            biz_item_db_id=biz_item_db_id,
            business_info=business_info,
            biz_item_info=biz_item_info,
            schedule_info=schedule_info,
            recommended_date=recommended_date,
            recommended_times=recommended_times,
            all_available_dates=all_available_dates,
            all_available_times=all_available_times,
            is_weekend=is_weekend,
            prices=prices,
            min_booking_count=min_booking_count,
            max_booking_count=max_booking_count,
        )

    async def parse_url_only(self, url: str) -> UrlImportResult:
        """
        URL 파싱만 수행합니다 (DB 저장 없음, API 조회만).

        Args:
            url: 네이버 예약 URL

        Returns:
            UrlImportResult: 파싱 결과
        """
        # 임시 DB 없이 조회만
        return await self.import_from_url(
            db=None,
            url=url,
            save_to_db=False,
            fetch_schedule=True
        )


# 싱글톤 인스턴스
url_import_service = UrlImportService()
