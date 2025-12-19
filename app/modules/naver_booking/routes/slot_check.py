"""
슬롯 조회 API 라우트
작성일: 2025-12-16
요구사항: REQ-MON-012 (슬롯 조회 API)

scripts/check_slots.py의 기능을 API 엔드포인트로 제공합니다.
"""
import re
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.business import Business
from app.models.biz_item import BizItem
from app.modules.naver_booking.services.graphql_client import (
    ScheduleInfo,
    get_naver_graphql_client,
)
from app.schemas.slot_check import (
    SlotCheckResponse,
    SlotCheckBusinessInfo,
    SlotCheckBizItemInfo,
    SlotCheckSummary,
    DateSlots,
    DateSummary,
    SlotInfo,
)

router = APIRouter(prefix="/api/v1/slots", tags=["slots"])

# 네이버 예약 URL 파싱 정규식
# 형식: https://booking.naver.com/booking/{type}/bizes/{business_id}/items/{biz_item_id}
# 또는: https://m.booking.naver.com/booking/{type}/bizes/{business_id}/items/{biz_item_id}
URL_PATTERN = re.compile(r'/bizes/(\d+)/items/(\d+)')

# 요일 매핑
DAY_OF_WEEK_KR = ["월", "화", "수", "목", "금", "토", "일"]


def parse_naver_url(url: str) -> tuple[str, str]:
    """
    네이버 예약 URL에서 business_id, biz_item_id 추출

    Args:
        url: 네이버 예약 URL

    Returns:
        (business_id, biz_item_id) 튜플

    Raises:
        HTTPException: URL 형식이 잘못된 경우
    """
    match = URL_PATTERN.search(url)
    if not match:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_URL",
                "message": "URL 형식이 올바르지 않습니다. 예: https://booking.naver.com/booking/13/bizes/1269828/items/6309738"
            }
        )
    return match.group(1), match.group(2)


def build_response(
    business_id: str,
    business_name: str,
    business_type_id: Optional[int],
    biz_item_id: str,
    biz_item_name: str,
    schedule: ScheduleInfo
) -> SlotCheckResponse:
    """
    조회 결과를 API 응답 형식으로 변환
    """
    slots_by_date = []
    total_available_slots = 0

    for date in sorted(schedule.slots_by_date.keys()):
        date_slots = schedule.slots_by_date[date]

        # 날짜에서 요일 계산
        dt = datetime.strptime(date, "%Y-%m-%d")
        day_of_week = DAY_OF_WEEK_KR[dt.weekday()]

        # 슬롯 정보 변환
        slot_infos = []
        date_capacity = 0
        date_booked = 0

        for slot in sorted(date_slots, key=lambda s: s.time):
            capacity = slot.unit_stock or 0
            booked = slot.unit_booking_count or 0
            remaining = capacity - booked
            is_available = remaining > 0 and slot.is_sale_day

            if is_available:
                total_available_slots += 1

            date_capacity += capacity
            date_booked += booked

            slot_infos.append(SlotInfo(
                time=slot.time,
                capacity=capacity,
                booked=booked,
                remaining=remaining,
                is_available=is_available
            ))

        date_remaining = date_capacity - date_booked

        slots_by_date.append(DateSlots(
            date=date,
            day_of_week=day_of_week,
            summary=DateSummary(
                total_capacity=date_capacity,
                total_booked=date_booked,
                total_remaining=date_remaining
            ),
            slots=slot_infos
        ))

    return SlotCheckResponse(
        business=SlotCheckBusinessInfo(
            business_id=business_id,
            name=business_name,
            business_type_id=business_type_id
        ),
        biz_item=SlotCheckBizItemInfo(
            biz_item_id=biz_item_id,
            name=biz_item_name
        ),
        summary=SlotCheckSummary(
            total_slots=len(schedule.slots),
            available_dates=schedule.available_dates,
            total_available_slots=total_available_slots
        ),
        slots_by_date=slots_by_date,
        queried_at=datetime.now()
    )


@router.get("/check", response_model=SlotCheckResponse)
async def check_slots(
    url: Optional[str] = Query(None, description="네이버 예약 URL"),
    business_id: Optional[str] = Query(None, description="업체 ID"),
    biz_item_id: Optional[str] = Query(None, description="상품 ID"),
    target_date: Optional[str] = Query(None, description="조회 시작일 (YYYY-MM-DD)"),
    days_ahead: int = Query(14, ge=1, le=35, description="조회 기간 (일)"),
    db: Session = Depends(get_db)
):
    """
    네이버 예약 슬롯 현황 조회

    URL 또는 business_id + biz_item_id로 조회 가능합니다.

    ## 사용 예시

    ### URL로 조회
    ```
    GET /api/v1/slots/check?url=https://booking.naver.com/booking/13/bizes/1269828/items/6309738
    ```

    ### ID로 조회
    ```
    GET /api/v1/slots/check?business_id=1269828&biz_item_id=6309738
    ```

    ## 응답
    - business: 업체 정보
    - biz_item: 상품 정보
    - summary: 전체 요약 (총 슬롯 수, 예약 가능 날짜 등)
    - slots_by_date: 날짜별 슬롯 상세 정보
    """
    # 파라미터 검증
    if url:
        business_id, biz_item_id = parse_naver_url(url)
    elif not (business_id and biz_item_id):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_PARAMS",
                "message": "url 또는 business_id + biz_item_id가 필요합니다"
            }
        )

    client = get_naver_graphql_client()

    # 1. 업체 정보: 로컬 DB → GraphQL → 기본값
    business = db.query(Business).filter(Business.business_id == business_id).first()
    if not business:
        # DB에 없으면 GraphQL 조회
        business_info = await client.fetch_business_info(business_id)
        business_name = business_info.name if business_info else "(미등록 업체)"
        business_type_id = (business_info.business_type_id if business_info else None) or 13
    else:
        business_name = business.name
        business_type_id = business.business_type_id or 13

    # 2. 상품 정보: 로컬 DB → GraphQL → 기본값
    biz_item = db.query(BizItem).filter(BizItem.biz_item_id == biz_item_id).first()
    if not biz_item:
        # DB에 없으면 GraphQL 조회
        biz_item_info = await client.fetch_biz_item(business_id, biz_item_id)
        biz_item_name = biz_item_info.name if biz_item_info else "(미등록 상품)"
    else:
        biz_item_name = biz_item.name

    # 3. GraphQL로 스케줄 조회 (핵심 - 실패 시 에러)
    start_date = target_date or datetime.now().strftime("%Y-%m-%d")
    schedule = await client.fetch_schedule(
        business_type_id=business_type_id,
        business_id=business_id,
        biz_item_id=biz_item_id,
        start_date=start_date,
        days_ahead=days_ahead
    )

    if not schedule:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "SCHEDULE_ERROR",
                "message": "스케줄 조회에 실패했습니다"
            }
        )

    # 4. 응답 변환
    return build_response(
        business_id=business_id,
        business_name=business_name,
        business_type_id=business_type_id,
        biz_item_id=biz_item_id,
        biz_item_name=biz_item_name,
        schedule=schedule
    )
