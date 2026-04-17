"""
Business 라우트 - 업체 API
설계 문서: 2025-12-01_monitoring_restructure_design.md
업데이트: 2025-12-03 - GraphQL API 상세정보 조회 기능 추가 (REQ-DATA-004)
"""
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.business import (
    Business,
    BusinessCreate,
    BusinessUpdate,
    BusinessWithItems,
    UrlImportRequest,
    UrlImportResponse,
)
from app.schemas.biz_item import BizItem, BizItemCreate, BizItemUpdate
from app.schemas.monitor_schedule import MonitorScheduleCreate
from app.modules.naver_booking.services.business_service import business_service
from app.modules.naver_booking.services.biz_item_service import biz_item_service
from app.services.schedule_service import schedule_service
from app.modules.naver_booking.services.graphql_client import (
    get_naver_graphql_client,
    BusinessInfo,
    BizItemInfo,
)
from app.modules.naver_booking.utils.parsers import parse_naver_booking_url
from app.utils.parsers import extract_date_only
from app.config import logger

router = APIRouter(prefix="/api/v1/businesses", tags=["businesses"])


@router.get("/", response_model=List[Business])
def get_businesses(
    service_type: str = None,
    recent_days: int = None,
    db: Session = Depends(get_db),
):
    """
    전체 업체 목록 조회

    - service_type: 서비스 타입 필터 (예: "naver", "coupang")
    - recent_days: 최근 N일 이내 업데이트된 업체만 조회
    """
    return business_service.get_all(db, service_type=service_type, recent_days=recent_days)


@router.post("/", response_model=Business, status_code=201)
def create_business(data: BusinessCreate, db: Session = Depends(get_db)):
    """업체 생성"""
    # 중복 체크
    existing = business_service.get_by_business_id(db, data.business_id)
    if existing:
        raise HTTPException(status_code=400, detail=f"Business with business_id '{data.business_id}' already exists")

    return business_service.create(db, data)


@router.get("/{business_id}", response_model=BusinessWithItems)
def get_business(business_id: int, db: Session = Depends(get_db)):
    """업체 상세 조회 (아이템 포함)"""
    business = business_service.get_by_id(db, business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.put("/{business_id}", response_model=Business)
def update_business(business_id: int, data: BusinessUpdate, db: Session = Depends(get_db)):
    """업체 수정"""
    business = business_service.update(db, business_id, data)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.delete("/{business_id}", status_code=204)
def delete_business(business_id: int, db: Session = Depends(get_db)):
    """업체 삭제 (하위 아이템/일정 모두 삭제)"""
    success = business_service.delete(db, business_id)
    if not success:
        raise HTTPException(status_code=404, detail="Business not found")
    return None


@router.get("/{business_id}/items", response_model=List[BizItem])
def get_business_items(business_id: int, db: Session = Depends(get_db)):
    """업체의 아이템 목록 조회"""
    business = business_service.get_by_id(db, business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    return biz_item_service.get_by_business(db, business_id)


@router.post("/import-url", response_model=UrlImportResponse)
async def import_from_url(data: UrlImportRequest, db: Session = Depends(get_db)):
    """
    URL에서 업체/아이템/일정을 자동 생성합니다.

    URL 형식: /booking/{category}/bizes/{businessId}/items/{itemId}?startDateTime=...

    - 업체가 없으면 자동 생성 (GraphQL API로 상세정보 조회)
    - 아이템이 없으면 자동 생성 (GraphQL API로 상세정보 조회)
    - 날짜가 URL에 있으면 일정도 자동 생성

    REQ-DATA-004: fetch_details=True이면 네이버 GraphQL API로 상세정보 자동 조회
    """
    # URL 파싱
    parsed = parse_naver_booking_url(data.url)

    if not parsed.is_valid:
        return UrlImportResponse(
            success=False,
            message=f"URL 파싱 실패: {parsed.error}",
            parsed_info={"url": data.url}
        )

    # GraphQL API로 상세정보 조회 (REQ-DATA-004)
    business_info: BusinessInfo = None
    biz_item_info: BizItemInfo = None
    business_details_dict = None
    item_details_dict = None

    if data.fetch_details:
        try:
            client = get_naver_graphql_client()
            result = await client.fetch_all_info(parsed.business_id, parsed.item_id)
            business_info = result.get("business")
            biz_item_info = result.get("item")

            if business_info:
                business_details_dict = {
                    "name": business_info.name,
                    "service_name": business_info.service_name,
                    "road_address": business_info.road_address,
                    "latitude": business_info.latitude,
                    "longitude": business_info.longitude,
                    "phone": business_info.phone,
                }
            if biz_item_info:
                item_details_dict = {
                    "name": biz_item_info.name,
                    "description": biz_item_info.description,
                    "biz_item_type": biz_item_info.biz_item_type,
                    "min_booking_count": biz_item_info.min_booking_count,
                    "max_booking_count": biz_item_info.max_booking_count,
                }
        except Exception as e:
            logger.warning(f"[import-url] GraphQL API 조회 실패: {e}")

    # 1. 업체 조회 또는 생성
    business = business_service.get_by_business_id(db, parsed.business_id)
    is_new_business = business is None

    if not business:
        # 업체명 결정: 사용자 입력 > API 조회 > 기본값
        business_name = data.business_name
        if not business_name and business_info:
            business_name = business_info.name
        if not business_name:
            business_name = f"Business_{parsed.business_id}"

        business_type_id = int(parsed.business_type_id) if parsed.business_type_id else None
        if not business_type_id and business_info:
            business_type_id = business_info.business_type_id

        business_data = BusinessCreate(
            business_id=parsed.business_id,
            business_type_id=business_type_id,
            place_id=business_info.place_id if business_info else None,
            name=business_name,
            service_type="naver",
            category=parsed.category,
            service_name=business_info.service_name if business_info else None,
            road_address=business_info.road_address if business_info else None,
            jibun_address=business_info.jibun_address if business_info else None,
            detail_address=business_info.detail_address if business_info else None,
            latitude=business_info.latitude if business_info else None,
            longitude=business_info.longitude if business_info else None,
            phone=business_info.phone if business_info else None,
            is_enabled=True
        )
        business = business_service.create(db, business_data)

        # API 동기화 시간 설정
        if business_info:
            business.api_synced_at = datetime.now()
            db.commit()
    else:
        # 기존 업체에 상세정보 업데이트 (API 동기화되지 않은 경우)
        if business_info and not business.api_synced_at:
            update_data = BusinessUpdate(
                place_id=business_info.place_id,
                service_name=business_info.service_name,
                road_address=business_info.road_address,
                jibun_address=business_info.jibun_address,
                detail_address=business_info.detail_address,
                latitude=business_info.latitude,
                longitude=business_info.longitude,
                phone=business_info.phone,
            )
            business = business_service.update(db, business.id, update_data)
            business.api_synced_at = datetime.now()
            db.commit()

    # 2. 아이템 조회 또는 생성
    item = biz_item_service.get_by_biz_item_id(db, business.id, parsed.item_id)
    is_new_item = item is None

    if not item:
        # 아이템명 결정: 사용자 입력 > API 조회 > 기본값
        item_name = data.item_name
        if not item_name and biz_item_info:
            item_name = biz_item_info.name
        if not item_name:
            item_name = f"Item_{parsed.item_id}"

        item_data = BizItemCreate(
            business_id=business.id,
            biz_item_id=parsed.item_id,
            name=item_name,
            description=biz_item_info.description if biz_item_info else None,
            biz_item_type=biz_item_info.biz_item_type if biz_item_info else None,
            biz_item_sub_type=biz_item_info.biz_item_sub_type if biz_item_info else None,
            booking_count_type=biz_item_info.booking_count_type if biz_item_info else None,
            min_booking_count=biz_item_info.min_booking_count if biz_item_info else None,
            max_booking_count=biz_item_info.max_booking_count if biz_item_info else None,
            start_date=biz_item_info.start_date if biz_item_info else None,
            end_date=biz_item_info.end_date if biz_item_info else None,
            extra_desc_json=biz_item_info.extra_desc_json if biz_item_info else None,
            booking_precaution_json=biz_item_info.booking_precaution_json if biz_item_info else None,
            is_enabled=True,
            time_range=data.time_range,
            auto_booking_enabled=data.auto_booking_enabled,
            max_bookings_per_schedule=data.max_bookings_per_schedule
        )
        item = biz_item_service.create(db, item_data)

        # API 동기화 시간 설정
        if biz_item_info:
            item.api_synced_at = datetime.now()
            db.commit()
    else:
        # 기존 아이템에 상세정보 업데이트 (API 동기화되지 않은 경우)
        if biz_item_info and not item.api_synced_at:
            update_data = BizItemUpdate(
                description=biz_item_info.description,
                biz_item_type=biz_item_info.biz_item_type,
                biz_item_sub_type=biz_item_info.biz_item_sub_type,
                booking_count_type=biz_item_info.booking_count_type,
                min_booking_count=biz_item_info.min_booking_count,
                max_booking_count=biz_item_info.max_booking_count,
                start_date=biz_item_info.start_date,
                end_date=biz_item_info.end_date,
                extra_desc_json=biz_item_info.extra_desc_json,
                booking_precaution_json=biz_item_info.booking_precaution_json,
            )
            item = biz_item_service.update(db, item.id, update_data)
            item.api_synced_at = datetime.now()
            db.commit()

    # 3. 일정 생성 (날짜가 있는 경우)
    schedule_id = None
    date_str = extract_date_only(parsed.start_date)
    if date_str:
        # 이미 존재하는 일정인지 확인
        existing = schedule_service.get_by_date(db, item.id, date_str)
        if not existing:
            schedule_data = MonitorScheduleCreate(
                biz_item_id=item.id,
                date=date_str,
                is_enabled=True
            )
            schedule = schedule_service.create(db, schedule_data)
            schedule_id = schedule.id
        else:
            schedule_id = existing.id

    # 결과 메시지 구성
    messages = []
    if is_new_business:
        messages.append(f"업체 '{business.name}' 생성")
    if is_new_item:
        messages.append(f"아이템 '{item.name}' 생성")
    if schedule_id:
        messages.append(f"일정 {date_str} 등록")
    if business_info:
        messages.append("API 상세정보 동기화 완료")

    return UrlImportResponse(
        success=True,
        message=" / ".join(messages) if messages else f"이미 등록: 업체 '{business.name}' / 아이템 '{item.name}'",
        business_id=business.id,
        item_id=item.id,
        schedule_id=schedule_id,
        parsed_info={
            "category": parsed.category,
            "naver_business_id": parsed.business_id,
            "naver_item_id": parsed.item_id,
            "date": date_str,
            "business_type_id": parsed.business_type_id
        },
        business_details=business_details_dict,
        item_details=item_details_dict,
        business=business,
        biz_item=item
    )


@router.post("/{business_id}/sync", response_model=Business)
async def sync_business_from_api(business_id: int, db: Session = Depends(get_db)):
    """
    기존 업체 정보를 네이버 GraphQL API에서 다시 조회하여 동기화합니다.
    (REQ-DATA-004)
    """
    business = business_service.get_by_id(db, business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    try:
        client = get_naver_graphql_client()
        business_info = await client.fetch_business_info(business.business_id)

        if not business_info:
            raise HTTPException(status_code=502, detail="네이버 API에서 업체 정보를 조회할 수 없습니다.")

        update_data = BusinessUpdate(
            name=business_info.name,
            place_id=business_info.place_id,
            business_type_id=business_info.business_type_id,
            service_name=business_info.service_name,
            road_address=business_info.road_address,
            jibun_address=business_info.jibun_address,
            detail_address=business_info.detail_address,
            latitude=business_info.latitude,
            longitude=business_info.longitude,
            phone=business_info.phone,
        )
        business = business_service.update(db, business_id, update_data)
        business.api_synced_at = datetime.now()
        db.commit()
        db.refresh(business)

        return business

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[sync_business] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
