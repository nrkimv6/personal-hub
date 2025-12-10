"""
NaverGraphQLClient - 네이버 예약 GraphQL API 클라이언트
작성일: 2025-12-03
요구사항: REQ-DATA-004 (업체/상품 상세정보 조회)

네이버 예약 GraphQL API를 통해 업체(Business) 및 상품(BizItem) 정보를 조회합니다.
"""
import aiohttp
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from app.config import logger


# GraphQL 엔드포인트
NAVER_GRAPHQL_ENDPOINT = "https://m.booking.naver.com/graphql"

# User-Agent (모바일 브라우저 에뮬레이션)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)


@dataclass
class BusinessInfo:
    """업체 정보 데이터 클래스"""
    business_id: str
    name: str
    business_type_id: Optional[int] = None
    place_id: Optional[str] = None
    service_name: Optional[str] = None
    road_address: Optional[str] = None
    jibun_address: Optional[str] = None
    detail_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = None
    category: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BizItemInfo:
    """상품 정보 데이터 클래스"""
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
    extra_desc_json: Optional[str] = None
    booking_precaution_json: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleSlot:
    """예약 가능 슬롯 정보"""
    slot_id: str
    start_time: str  # "2025-12-20 11:30:00" 형식
    date: str  # "2025-12-20"
    time: str  # "11:30"
    is_business_day: bool
    is_sale_day: bool
    stock: int
    unit_stock: int
    unit_booking_count: int
    duration: int
    min_booking_count: int
    max_booking_count: int
    prices: List[Dict[str, Any]] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleInfo:
    """스케줄 조회 결과"""
    business_id: str
    biz_item_id: str
    available_dates: List[str]  # 예약 가능한 날짜 목록
    slots: List[ScheduleSlot]  # 모든 슬롯 정보
    slots_by_date: Dict[str, List[ScheduleSlot]] = field(default_factory=dict)  # 날짜별 슬롯


class NaverGraphQLClient:
    """네이버 예약 GraphQL API 클라이언트"""

    # Business 쿼리 (업체 정보)
    # Note: addressJson, phoneInformationJson은 JSON 타입이므로 하위 필드 선택 불가
    BUSINESS_QUERY = """
    query business($input: BusinessParams) {
        business(input: $input) {
            id
            businessId
            businessTypeId
            placeId
            name
            serviceName
            coordinates
            addressJson
            phoneInformationJson
            bookingAvailableCode
            bookingAvailableValue
            __typename
        }
    }
    """

    # BizItems 쿼리 (상품 목록)
    # Note: 스키마 변경으로 bookingPrecautionJson은 하위 필드 필요, extraDescJson은 JSON 타입
    BIZ_ITEMS_QUERY = """
    query bizItems($input: BizItemsParams) {
        bizItems(input: $input) {
            id
            bizItemId
            name
            desc
            bizItemType
            bizItemSubType
            bookingCountType
            startDate
            endDate
            extraDescJson
            bookingPrecautionJson {
                title
                desc
            }
            bookingCountSettingJson
            bookableSettingJson
            __typename
        }
    }
    """

    # Schedule 쿼리 (예약 가능 시간 및 가격 정보)
    SCHEDULE_QUERY = """
    query schedule($scheduleParams: ScheduleParams) {
        schedule(input: $scheduleParams) {
            bizItemSchedule {
                hourly {
                    isBusinessDay
                    isSaleDay
                    unitStock
                    unitBookingCount
                    stock
                    duration
                    minBookingCount
                    maxBookingCount
                    unitStartTime
                    slotId
                    prices {
                        priceId
                        name
                        price
                        normalPrice
                    }
                }
            }
        }
    }
    """

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        """
        Args:
            session: aiohttp 세션 (없으면 자동 생성)
        """
        self._session = session
        self._own_session = session is None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """세션이 없으면 생성"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def close(self):
        """세션 종료 (자체 생성한 경우만)"""
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def _execute_query(
        self,
        query: str,
        variables: Dict[str, Any],
        operation_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        GraphQL 쿼리를 실행합니다.

        Args:
            query: GraphQL 쿼리 문자열
            variables: 쿼리 변수
            operation_name: 오퍼레이션 이름

        Returns:
            Dict: API 응답 데이터 또는 None
        """
        session = await self._ensure_session()

        headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "user-agent": DEFAULT_USER_AGENT,
            "origin": "https://m.booking.naver.com",
            "referer": "https://m.booking.naver.com/",
        }

        payload = {
            "operationName": operation_name,
            "variables": variables,
            "query": query
        }

        try:
            async with session.post(
                f"{NAVER_GRAPHQL_ENDPOINT}?opName={operation_name}",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    logger.error(f"[NaverGraphQL] HTTP {response.status} for {operation_name}")
                    return None

                data = await response.json()

                if "errors" in data and data["errors"]:
                    logger.error(f"[NaverGraphQL] GraphQL errors: {data['errors']}")
                    return None

                return data.get("data")

        except aiohttp.ClientError as e:
            logger.error(f"[NaverGraphQL] Request error for {operation_name}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"[NaverGraphQL] JSON decode error for {operation_name}: {e}")
            return None

    async def fetch_business_info(
        self,
        business_id: str,
        projections: str = "RESOURCE,BUSINESS-AMENITY,BRAND-DISPLAY,BUSINESS_DETAIL"
    ) -> Optional[BusinessInfo]:
        """
        업체 정보를 조회합니다.

        Args:
            business_id: 네이버 업체 ID
            projections: 조회할 프로젝션 (기본값: 전체)

        Returns:
            BusinessInfo: 업체 정보 또는 None
        """
        variables = {
            "input": {
                "businessId": str(business_id),
                "lang": "ko",
                "projections": projections
            }
        }

        data = await self._execute_query(self.BUSINESS_QUERY, variables, "business")
        if not data or not data.get("business"):
            logger.warning(f"[NaverGraphQL] No business data for {business_id}")
            return None

        biz = data["business"]

        # 주소 파싱
        address_json = biz.get("addressJson", {}) or {}
        if isinstance(address_json, str):
            try:
                address_json = json.loads(address_json)
            except json.JSONDecodeError:
                address_json = {}

        # 전화번호 파싱
        phone_json = biz.get("phoneInformationJson", {}) or {}
        if isinstance(phone_json, str):
            try:
                phone_json = json.loads(phone_json)
            except json.JSONDecodeError:
                phone_json = {}

        # 좌표 파싱
        coordinates = biz.get("coordinates", [])
        latitude = None
        longitude = None
        if coordinates and len(coordinates) >= 2:
            longitude = coordinates[0]
            latitude = coordinates[1]

        return BusinessInfo(
            business_id=str(biz.get("businessId", business_id)),
            name=biz.get("name", ""),
            business_type_id=biz.get("businessTypeId"),
            place_id=biz.get("placeId"),
            service_name=biz.get("serviceName"),
            road_address=address_json.get("roadAddr"),
            jibun_address=address_json.get("jibunAddr"),
            detail_address=address_json.get("detailAddr"),
            latitude=latitude,
            longitude=longitude,
            phone=phone_json.get("reprPhone"),
            raw_data=biz
        )

    async def fetch_biz_items(
        self,
        business_id: str,
        projections: str = "RESOURCE"
    ) -> List[BizItemInfo]:
        """
        업체의 상품 목록을 조회합니다.

        Args:
            business_id: 네이버 업체 ID
            projections: 조회할 프로젝션

        Returns:
            List[BizItemInfo]: 상품 정보 목록
        """
        variables = {
            "input": {
                "businessId": str(business_id),
                "lang": "ko",
                "projections": projections
            }
        }

        data = await self._execute_query(self.BIZ_ITEMS_QUERY, variables, "bizItems")
        if not data or not data.get("bizItems"):
            logger.warning(f"[NaverGraphQL] No bizItems data for {business_id}")
            return []

        items = []
        for item in data["bizItems"]:
            # bookingCountSettingJson 파싱 (min/max 예약 인원)
            booking_count_setting = item.get("bookingCountSettingJson", {}) or {}
            if isinstance(booking_count_setting, str):
                try:
                    booking_count_setting = json.loads(booking_count_setting)
                except json.JSONDecodeError:
                    booking_count_setting = {}

            # extraDescJson, bookingPrecautionJson은 JSON 문자열로 저장
            extra_desc = item.get("extraDescJson")
            if extra_desc and not isinstance(extra_desc, str):
                extra_desc = json.dumps(extra_desc, ensure_ascii=False)

            booking_precaution = item.get("bookingPrecautionJson")
            if booking_precaution and not isinstance(booking_precaution, str):
                booking_precaution = json.dumps(booking_precaution, ensure_ascii=False)

            items.append(BizItemInfo(
                biz_item_id=str(item.get("bizItemId", "")),
                name=item.get("name", ""),
                description=item.get("desc"),
                biz_item_type=item.get("bizItemType"),
                biz_item_sub_type=item.get("bizItemSubType"),
                booking_count_type=item.get("bookingCountType"),
                min_booking_count=booking_count_setting.get("minBookingCount"),
                max_booking_count=booking_count_setting.get("maxBookingCount"),
                start_date=item.get("startDate"),
                end_date=item.get("endDate"),
                extra_desc_json=extra_desc,
                booking_precaution_json=booking_precaution,
                raw_data=item
            ))

        return items

    async def fetch_biz_item(
        self,
        business_id: str,
        biz_item_id: str
    ) -> Optional[BizItemInfo]:
        """
        특정 상품 정보를 조회합니다.

        Args:
            business_id: 네이버 업체 ID
            biz_item_id: 상품 ID

        Returns:
            BizItemInfo: 상품 정보 또는 None
        """
        items = await self.fetch_biz_items(business_id)
        for item in items:
            if str(item.biz_item_id) == str(biz_item_id):
                return item
        return None

    async def fetch_all_info(
        self,
        business_id: str,
        biz_item_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        업체와 상품 정보를 모두 조회합니다.

        Args:
            business_id: 네이버 업체 ID
            biz_item_id: 특정 상품 ID (옵션)

        Returns:
            Dict: {"business": BusinessInfo, "items": List[BizItemInfo], "item": BizItemInfo|None}
        """
        business_info = await self.fetch_business_info(business_id)
        items = await self.fetch_biz_items(business_id)

        target_item = None
        if biz_item_id:
            for item in items:
                if str(item.biz_item_id) == str(biz_item_id):
                    target_item = item
                    break

        return {
            "business": business_info,
            "items": items,
            "item": target_item
        }

    async def fetch_schedule(
        self,
        business_type_id: int,
        business_id: str,
        biz_item_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days_ahead: int = 35
    ) -> Optional[ScheduleInfo]:
        """
        예약 가능한 스케줄(날짜/시간/가격)을 조회합니다.

        Args:
            business_type_id: 업체 타입 ID (예: 5, 6)
            business_id: 네이버 업체 ID
            biz_item_id: 상품 ID
            start_date: 조회 시작일 (YYYY-MM-DD, 기본: 오늘)
            end_date: 조회 종료일 (YYYY-MM-DD, 기본: start_date + days_ahead)
            days_ahead: end_date가 없을 때 조회할 기간 (기본: 35일)

        Returns:
            ScheduleInfo: 스케줄 정보 또는 None
        """
        # 날짜 기본값 설정
        today = datetime.now()
        if not start_date:
            start_date = today.strftime("%Y-%m-%d")
        if not end_date:
            end_dt = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=days_ahead)
            end_date = end_dt.strftime("%Y-%m-%d")

        variables = {
            "scheduleParams": {
                "businessTypeId": int(business_type_id),
                "businessId": str(business_id),
                "bizItemId": str(biz_item_id),
                "startDateTime": f"{start_date}T00:00:00",
                "endDateTime": f"{end_date}T23:59:59",
                "fixedTime": True,
                "includesHolidaySchedules": True
            }
        }

        data = await self._execute_query(self.SCHEDULE_QUERY, variables, "schedule")
        if not data or not data.get("schedule"):
            logger.warning(f"[NaverGraphQL] No schedule data for {business_id}/{biz_item_id}")
            return None

        hourly = data["schedule"].get("bizItemSchedule", {}).get("hourly", [])
        if not hourly:
            logger.warning(f"[NaverGraphQL] Empty hourly schedule for {business_id}/{biz_item_id}")
            return ScheduleInfo(
                business_id=business_id,
                biz_item_id=biz_item_id,
                available_dates=[],
                slots=[],
                slots_by_date={}
            )

        slots = []
        slots_by_date: Dict[str, List[ScheduleSlot]] = {}
        available_dates_set = set()

        for slot_data in hourly:
            # "2025-12-20 11:30:00" 형식 파싱
            unit_start_time = slot_data.get("unitStartTime", "")
            if not unit_start_time:
                continue

            parts = unit_start_time.split(" ")
            slot_date = parts[0] if parts else ""
            slot_time_full = parts[1] if len(parts) > 1 else "00:00:00"
            slot_time = slot_time_full[:5]  # "11:30"

            # 예약 가능 여부 체크 (재고 있고, 판매일인 경우)
            # None 값 처리: API가 null을 반환할 수 있음
            stock_value = slot_data.get("stock") or 0
            is_available = (
                slot_data.get("isSaleDay", False) and
                stock_value > 0
            )

            slot = ScheduleSlot(
                slot_id=str(slot_data.get("slotId", "")),
                start_time=unit_start_time,
                date=slot_date,
                time=slot_time,
                is_business_day=slot_data.get("isBusinessDay", False),
                is_sale_day=slot_data.get("isSaleDay", False),
                stock=stock_value,
                unit_stock=slot_data.get("unitStock") or 0,
                unit_booking_count=slot_data.get("unitBookingCount") or 0,
                duration=slot_data.get("duration") or 0,
                min_booking_count=slot_data.get("minBookingCount") or 1,
                max_booking_count=slot_data.get("maxBookingCount") or 10,
                prices=slot_data.get("prices") or [],
                raw_data=slot_data
            )
            slots.append(slot)

            # 날짜별 그룹화
            if slot_date not in slots_by_date:
                slots_by_date[slot_date] = []
            slots_by_date[slot_date].append(slot)

            # 예약 가능한 날짜 수집
            if is_available:
                available_dates_set.add(slot_date)

        # 날짜 정렬
        available_dates = sorted(list(available_dates_set))

        return ScheduleInfo(
            business_id=business_id,
            biz_item_id=biz_item_id,
            available_dates=available_dates,
            slots=slots,
            slots_by_date=slots_by_date
        )

    def get_smart_time_slots(
        self,
        schedule_info: ScheduleInfo,
        target_date: Optional[str] = None,
        prefer_time_start: Optional[str] = None,
        prefer_time_end: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        스마트 시간 선택: 평일은 18:00 이후, 주말은 첫 시간

        Args:
            schedule_info: 스케줄 정보
            target_date: 대상 날짜 (없으면 첫 예약 가능일)
            prefer_time_start: 선호 시작 시간 (예: "18:00")
            prefer_time_end: 선호 종료 시간 (예: "21:00")

        Returns:
            Dict: {
                "target_date": str,
                "recommended_times": List[str],
                "all_available_times": List[str],
                "is_weekend": bool
            }
        """
        # 대상 날짜 결정
        if not target_date:
            if schedule_info.available_dates:
                target_date = schedule_info.available_dates[0]
            else:
                return {
                    "target_date": None,
                    "recommended_times": [],
                    "all_available_times": [],
                    "is_weekend": False,
                    "message": "예약 가능한 날짜가 없습니다."
                }

        # 해당 날짜의 슬롯 가져오기
        date_slots = schedule_info.slots_by_date.get(target_date, [])
        if not date_slots:
            return {
                "target_date": target_date,
                "recommended_times": [],
                "all_available_times": [],
                "is_weekend": False,
                "message": f"{target_date}에 예약 가능한 시간이 없습니다."
            }

        # 예약 가능한 시간만 필터링
        available_slots = [s for s in date_slots if s.is_sale_day and s.stock > 0]
        all_times = sorted([s.time for s in available_slots])

        # 주말/평일 판단
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        is_weekend = dt.weekday() >= 5  # 토(5), 일(6)

        # 시간 필터링
        recommended_times = []

        if prefer_time_start or prefer_time_end:
            # 사용자 지정 시간대 필터링
            for t in all_times:
                if prefer_time_start and t < prefer_time_start:
                    continue
                if prefer_time_end and t > prefer_time_end:
                    continue
                recommended_times.append(t)
        elif is_weekend:
            # 주말: 전체 시간 (첫 시간부터)
            recommended_times = all_times
        else:
            # 평일: 18:00 이후 우선
            recommended_times = [t for t in all_times if t >= "18:00"]
            # 18:00 이후가 없으면 전체 시간
            if not recommended_times:
                recommended_times = all_times

        return {
            "target_date": target_date,
            "recommended_times": recommended_times,
            "all_available_times": all_times,
            "is_weekend": is_weekend
        }


# 싱글톤 인스턴스 생성 함수
_client_instance: Optional[NaverGraphQLClient] = None


def get_naver_graphql_client() -> NaverGraphQLClient:
    """NaverGraphQLClient 싱글톤 인스턴스 반환"""
    global _client_instance
    if _client_instance is None:
        _client_instance = NaverGraphQLClient()
    return _client_instance


async def close_naver_graphql_client():
    """싱글톤 인스턴스 종료"""
    global _client_instance
    if _client_instance:
        await _client_instance.close()
        _client_instance = None
