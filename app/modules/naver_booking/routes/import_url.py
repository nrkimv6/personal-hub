"""
URL Import 라우트 - 통합 URL 임포트 API

네이버 예약 URL에서 정보를 추출하고 DB에 저장합니다.
작성일: 2025-12-03
"""
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.url_import_service import url_import_service
from app.config import logger


router = APIRouter(prefix="/api/v1/import", tags=["import"])


class UrlParseRequest(BaseModel):
    """URL 파싱/조회 요청"""
    url: str
    target_date: Optional[str] = None  # YYYY-MM-DD, 없으면 첫 가능일
    prefer_time_start: Optional[str] = None  # HH:MM, 예: "18:00"
    prefer_time_end: Optional[str] = None  # HH:MM, 예: "21:00"
    fetch_schedule: bool = True  # 스케줄 조회 여부


class UrlImportRequest(BaseModel):
    """URL 임포트 요청 (DB 저장 포함)"""
    url: str
    target_date: Optional[str] = None
    prefer_time_start: Optional[str] = None
    prefer_time_end: Optional[str] = None


class ParsedUrlInfo(BaseModel):
    """파싱된 URL 정보"""
    business_id: str
    biz_item_id: str
    business_type_id: Optional[str] = None
    category: Optional[str] = None
    start_date: Optional[str] = None


class BusinessDetails(BaseModel):
    """업체 상세 정보"""
    business_id: str
    name: str
    service_name: Optional[str] = None
    road_address: Optional[str] = None
    jibun_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = None


class ItemDetails(BaseModel):
    """상품 상세 정보"""
    biz_item_id: str
    name: str
    description: Optional[str] = None
    biz_item_type: Optional[str] = None
    biz_item_sub_type: Optional[str] = None
    booking_count_type: Optional[str] = None
    min_booking_count: Optional[int] = None
    max_booking_count: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ScheduleRecommendation(BaseModel):
    """스케줄 추천 정보"""
    target_date: Optional[str] = None
    is_weekend: bool = False
    recommended_times: List[str] = []
    all_available_times: List[str] = []
    all_available_dates: List[str] = []
    prices: List[Dict[str, Any]] = []
    min_booking_count: Optional[int] = None
    max_booking_count: Optional[int] = None


class UrlParseResponse(BaseModel):
    """URL 파싱/조회 응답 (DB 저장 없음)"""
    success: bool
    message: str
    parsed_url: Optional[ParsedUrlInfo] = None
    business: Optional[BusinessDetails] = None
    item: Optional[ItemDetails] = None
    schedule: Optional[ScheduleRecommendation] = None


class UrlImportResponse(BaseModel):
    """URL 임포트 응답 (DB 저장 포함)"""
    success: bool
    message: str
    business_db_id: Optional[int] = None
    biz_item_db_id: Optional[int] = None
    parsed_url: Optional[ParsedUrlInfo] = None
    business: Optional[BusinessDetails] = None
    item: Optional[ItemDetails] = None
    schedule: Optional[ScheduleRecommendation] = None


@router.post("/parse-url", response_model=UrlParseResponse)
async def parse_url(data: UrlParseRequest):
    """
    URL을 파싱하고 정보를 조회합니다 (DB 저장 없음).

    - URL에서 business_id, biz_item_id 추출
    - GraphQL API로 업체/상품 상세정보 조회
    - 예약 가능 날짜/시간 조회 (fetch_schedule=True)
    - 스마트 시간 추천 (평일 18:00 이후, 주말 전체)
    """
    result = await url_import_service.import_from_url(
        db=None,
        url=data.url,
        target_date=data.target_date,
        prefer_time_start=data.prefer_time_start,
        prefer_time_end=data.prefer_time_end,
        fetch_schedule=data.fetch_schedule,
        save_to_db=False
    )

    if not result.success:
        return UrlParseResponse(
            success=False,
            message=result.message
        )

    # 응답 구성
    parsed_url = None
    if result.parsed_url:
        parsed_url = ParsedUrlInfo(
            business_id=result.parsed_url.business_id,
            biz_item_id=result.parsed_url.item_id,
            business_type_id=result.parsed_url.business_type_id,
            category=result.parsed_url.category,
            start_date=result.parsed_url.start_date
        )

    business = None
    if result.business_info:
        business = BusinessDetails(
            business_id=result.business_info.business_id,
            name=result.business_info.name,
            service_name=result.business_info.service_name,
            road_address=result.business_info.road_address,
            jibun_address=result.business_info.jibun_address,
            latitude=result.business_info.latitude,
            longitude=result.business_info.longitude,
            phone=result.business_info.phone
        )

    item = None
    if result.biz_item_info:
        item = ItemDetails(
            biz_item_id=result.biz_item_info.biz_item_id,
            name=result.biz_item_info.name,
            description=result.biz_item_info.description,
            biz_item_type=result.biz_item_info.biz_item_type,
            biz_item_sub_type=result.biz_item_info.biz_item_sub_type,
            booking_count_type=result.biz_item_info.booking_count_type,
            min_booking_count=result.biz_item_info.min_booking_count,
            max_booking_count=result.biz_item_info.max_booking_count,
            start_date=result.biz_item_info.start_date,
            end_date=result.biz_item_info.end_date
        )

    schedule = ScheduleRecommendation(
        target_date=result.recommended_date,
        is_weekend=result.is_weekend,
        recommended_times=result.recommended_times,
        all_available_times=result.all_available_times,
        all_available_dates=result.all_available_dates,
        prices=result.prices,
        min_booking_count=result.min_booking_count,
        max_booking_count=result.max_booking_count
    )

    return UrlParseResponse(
        success=True,
        message=result.message,
        parsed_url=parsed_url,
        business=business,
        item=item,
        schedule=schedule
    )


@router.post("/url", response_model=UrlImportResponse)
async def import_url(data: UrlImportRequest, db: Session = Depends(get_db)):
    """
    URL을 파싱하고 정보를 DB에 저장합니다.

    - URL에서 business_id, biz_item_id 추출
    - GraphQL API로 업체/상품 상세정보 조회
    - businesses, biz_items 테이블에 upsert
    - 예약 가능 날짜/시간 정보도 함께 반환
    """
    result = await url_import_service.import_from_url(
        db=db,
        url=data.url,
        target_date=data.target_date,
        prefer_time_start=data.prefer_time_start,
        prefer_time_end=data.prefer_time_end,
        fetch_schedule=True,
        save_to_db=True
    )

    if not result.success:
        return UrlImportResponse(
            success=False,
            message=result.message
        )

    # 응답 구성
    parsed_url = None
    if result.parsed_url:
        parsed_url = ParsedUrlInfo(
            business_id=result.parsed_url.business_id,
            biz_item_id=result.parsed_url.item_id,
            business_type_id=result.parsed_url.business_type_id,
            category=result.parsed_url.category,
            start_date=result.parsed_url.start_date
        )

    business = None
    if result.business_info:
        business = BusinessDetails(
            business_id=result.business_info.business_id,
            name=result.business_info.name,
            service_name=result.business_info.service_name,
            road_address=result.business_info.road_address,
            jibun_address=result.business_info.jibun_address,
            latitude=result.business_info.latitude,
            longitude=result.business_info.longitude,
            phone=result.business_info.phone
        )

    item = None
    if result.biz_item_info:
        item = ItemDetails(
            biz_item_id=result.biz_item_info.biz_item_id,
            name=result.biz_item_info.name,
            description=result.biz_item_info.description,
            biz_item_type=result.biz_item_info.biz_item_type,
            biz_item_sub_type=result.biz_item_info.biz_item_sub_type,
            booking_count_type=result.biz_item_info.booking_count_type,
            min_booking_count=result.biz_item_info.min_booking_count,
            max_booking_count=result.biz_item_info.max_booking_count,
            start_date=result.biz_item_info.start_date,
            end_date=result.biz_item_info.end_date
        )

    schedule = ScheduleRecommendation(
        target_date=result.recommended_date,
        is_weekend=result.is_weekend,
        recommended_times=result.recommended_times,
        all_available_times=result.all_available_times,
        all_available_dates=result.all_available_dates,
        prices=result.prices,
        min_booking_count=result.min_booking_count,
        max_booking_count=result.max_booking_count
    )

    return UrlImportResponse(
        success=True,
        message=result.message,
        business_db_id=result.business_db_id,
        biz_item_db_id=result.biz_item_db_id,
        parsed_url=parsed_url,
        business=business,
        item=item,
        schedule=schedule
    )
