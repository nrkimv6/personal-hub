"""
NaverGraphQLClient 테스트
작성일: 2025-12-03
요구사항: REQ-DATA-004 (업체/상품 상세정보 조회)

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

CORRECT 조건 적용:
- Conformance: 형식 준수
- Ordering: 순서 보장
- Range: 범위 검증
- Reference: 참조 검증
- Existence: 존재 여부
- Cardinality: 개수 검증
- Time: 시간 관련 테스트
"""

import pytest
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, patch, MagicMock
from dataclasses import asdict

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.naver_graphql_client import (
    NaverGraphQLClient,
    BusinessInfo,
    BizItemInfo,
    ScheduleInfo,
    ScheduleSlot,
    DualCheckResult,
    get_naver_graphql_client,
    NAVER_GRAPHQL_ENDPOINT,
)


# ============================================================
# 테스트 픽스처
# ============================================================

@pytest.fixture
def sample_business_api_response():
    """네이버 API 업체 응답 샘플"""
    return {
        "data": {
            "business": {
                "id": "Business:1543589",
                "businessId": "1543589",
                "businessTypeId": 6,
                "placeId": "2082132012",
                "name": "하우스 오브 애슐리 House of Ashley",
                "serviceName": "디저트 뮤지엄 DESSERT MUSEUM",
                "coordinates": [127.0658895, 37.5463938],
                "addressJson": {
                    "roadAddr": "서울특별시 성동구 아차산로17길 48, B1 애슐리퀸즈",
                    "jibunAddr": "서울특별시 성동구 성수동2가 273-13",
                    "detailAddr": "B1"
                },
                "phoneInformationJson": {
                    "reprPhone": "010-9189-1643"
                },
                "bookingAvailableCode": "RI01",
                "bookingAvailableValue": 0,
                "__typename": "Business"
            }
        }
    }


@pytest.fixture
def sample_biz_items_api_response():
    """네이버 API 상품 목록 응답 샘플"""
    return {
        "data": {
            "bizItems": [
                {
                    "id": "BizItem:7227340",
                    "bizItemId": "7227340",
                    "name": "[사전예약 얼리버드]디저트뮤지엄 DESSERT MUSEUM (12.20~12.21)",
                    "desc": "디저트 뮤지엄 입장권입니다.",
                    "bizItemType": "STANDARD",
                    "bizItemSubType": "RESTAURANT_VISIT",
                    "bookingCountType": "PERSON",
                    "startDate": "2025-11-25",
                    "endDate": "2025-12-31",
                    "extraDescJson": [
                        {"title": "[디저트 뮤지엄 이용 유의사항]", "context": "내용..."}
                    ],
                    "bookingPrecautionJson": [
                        {"title": None, "desc": "예약 주의사항입니다."}
                    ],
                    "bookingCountSettingJson": {
                        "minBookingCount": 2,
                        "maxBookingCount": 4
                    },
                    "bookableSettingJson": {
                        "isOpened": True,
                        "isPaused": False,
                        "openDateTime": "2025-12-03T12:00:00+09:00"
                    },
                    "__typename": "BizItem"
                },
                {
                    "id": "BizItem:7227341",
                    "bizItemId": "7227341",
                    "name": "디저트뮤지엄 정규 입장권",
                    "desc": "정규 입장권입니다.",
                    "bizItemType": "STANDARD",
                    "bizItemSubType": "RESTAURANT_VISIT",
                    "bookingCountType": "PERSON",
                    "startDate": "2025-01-01",
                    "endDate": None,
                    "extraDescJson": None,
                    "bookingPrecautionJson": None,
                    "bookingCountSettingJson": {
                        "minBookingCount": 1,
                        "maxBookingCount": 10
                    },
                    "bookableSettingJson": {
                        "isOpened": True,
                        "isPaused": False
                    },
                    "__typename": "BizItem"
                }
            ]
        }
    }


@pytest.fixture
def mock_aiohttp_session():
    """모의 aiohttp 세션"""
    session = AsyncMock()
    return session


# ============================================================
# 1. BusinessInfo 데이터클래스 테스트
# ============================================================

class TestBusinessInfo:
    """BusinessInfo 데이터클래스 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_business_info_creation(self):
        """
        [Right] BusinessInfo가 올바르게 생성되는지
        """
        info = BusinessInfo(
            business_id="1543589",
            name="테스트 업체",
            business_type_id=6,
            place_id="2082132012",
            service_name="테스트 서비스",
            road_address="서울시 강남구",
            latitude=37.5,
            longitude=127.0,
            phone="010-1234-5678"
        )

        assert info.business_id == "1543589"
        assert info.name == "테스트 업체"
        assert info.business_type_id == 6
        assert info.latitude == 37.5
        assert info.longitude == 127.0

    def test_right_business_info_optional_fields(self):
        """
        [Right] 선택적 필드가 None으로 기본값 설정되는지
        """
        info = BusinessInfo(
            business_id="123",
            name="테스트"
        )

        assert info.place_id is None
        assert info.service_name is None
        assert info.road_address is None
        assert info.latitude is None
        assert info.phone is None

    # --- Conformance: 형식 준수 ---

    def test_conformance_business_id_string(self):
        """
        [Conformance] business_id가 문자열인지
        """
        info = BusinessInfo(
            business_id="1543589",
            name="테스트"
        )

        assert isinstance(info.business_id, str)

    # --- Range: 범위 검증 ---

    def test_range_coordinates_valid(self):
        """
        [Range] 좌표값이 유효한 범위인지 (한국 내)
        """
        info = BusinessInfo(
            business_id="123",
            name="테스트",
            latitude=37.5463938,
            longitude=127.0658895
        )

        # 한국 좌표 범위 (대략)
        assert 33 <= info.latitude <= 43
        assert 124 <= info.longitude <= 132


# ============================================================
# 2. BizItemInfo 데이터클래스 테스트
# ============================================================

class TestBizItemInfo:
    """BizItemInfo 데이터클래스 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_biz_item_info_creation(self):
        """
        [Right] BizItemInfo가 올바르게 생성되는지
        """
        info = BizItemInfo(
            biz_item_id="7227340",
            name="테스트 상품",
            description="상품 설명",
            biz_item_type="STANDARD",
            biz_item_sub_type="RESTAURANT_VISIT",
            booking_count_type="PERSON",
            min_booking_count=2,
            max_booking_count=4
        )

        assert info.biz_item_id == "7227340"
        assert info.name == "테스트 상품"
        assert info.min_booking_count == 2
        assert info.max_booking_count == 4

    # --- Boundary: 경계값 테스트 ---

    def test_boundary_min_max_booking_count(self):
        """
        [Boundary] min_booking_count <= max_booking_count
        """
        info = BizItemInfo(
            biz_item_id="123",
            name="테스트",
            min_booking_count=2,
            max_booking_count=4
        )

        assert info.min_booking_count <= info.max_booking_count

    def test_boundary_booking_count_none(self):
        """
        [Boundary] 예약 인원이 None일 수 있음
        """
        info = BizItemInfo(
            biz_item_id="123",
            name="테스트"
        )

        assert info.min_booking_count is None
        assert info.max_booking_count is None


# ============================================================
# 3. NaverGraphQLClient 테스트
# ============================================================

class TestNaverGraphQLClient:
    """NaverGraphQLClient 테스트"""

    # --- Right: 결과가 올바른가? ---

    @pytest.mark.asyncio
    async def test_right_fetch_business_info_parsing(self, sample_business_api_response):
        """
        [Right] fetch_business_info가 API 응답을 올바르게 파싱하는지
        """
        with patch.object(NaverGraphQLClient, '_execute_query', new_callable=AsyncMock) as mock_query:
            mock_query.return_value = sample_business_api_response["data"]

            client = NaverGraphQLClient()
            result = await client.fetch_business_info("1543589")

            assert result is not None
            assert result.business_id == "1543589"
            assert result.name == "하우스 오브 애슐리 House of Ashley"
            assert result.service_name == "디저트 뮤지엄 DESSERT MUSEUM"
            assert result.road_address == "서울특별시 성동구 아차산로17길 48, B1 애슐리퀸즈"
            assert result.latitude == 37.5463938
            assert result.longitude == 127.0658895
            assert result.phone == "010-9189-1643"

            await client.close()

    @pytest.mark.asyncio
    async def test_right_fetch_biz_items_parsing(self, sample_biz_items_api_response):
        """
        [Right] fetch_biz_items가 API 응답을 올바르게 파싱하는지
        """
        with patch.object(NaverGraphQLClient, '_execute_query', new_callable=AsyncMock) as mock_query:
            mock_query.return_value = sample_biz_items_api_response["data"]

            client = NaverGraphQLClient()
            result = await client.fetch_biz_items("1543589")

            assert len(result) == 2
            assert result[0].biz_item_id == "7227340"
            assert result[0].name == "[사전예약 얼리버드]디저트뮤지엄 DESSERT MUSEUM (12.20~12.21)"
            assert result[0].biz_item_type == "STANDARD"
            assert result[0].min_booking_count == 2
            assert result[0].max_booking_count == 4

            await client.close()

    @pytest.mark.asyncio
    async def test_right_fetch_biz_item_single(self, sample_biz_items_api_response):
        """
        [Right] fetch_biz_item이 특정 아이템만 반환하는지
        """
        with patch.object(NaverGraphQLClient, '_execute_query', new_callable=AsyncMock) as mock_query:
            mock_query.return_value = sample_biz_items_api_response["data"]

            client = NaverGraphQLClient()
            result = await client.fetch_biz_item("1543589", "7227340")

            assert result is not None
            assert result.biz_item_id == "7227340"

            await client.close()

    @pytest.mark.asyncio
    async def test_right_fetch_all_info(self, sample_business_api_response, sample_biz_items_api_response):
        """
        [Right] fetch_all_info가 업체와 상품 정보를 모두 반환하는지
        """
        with patch.object(NaverGraphQLClient, '_execute_query', new_callable=AsyncMock) as mock_query:
            # 첫 호출은 business, 두 번째는 bizItems
            mock_query.side_effect = [
                sample_business_api_response["data"],
                sample_biz_items_api_response["data"]
            ]

            client = NaverGraphQLClient()
            result = await client.fetch_all_info("1543589", "7227340")

            assert "business" in result
            assert "items" in result
            assert "item" in result

            assert result["business"].business_id == "1543589"
            assert len(result["items"]) == 2
            assert result["item"].biz_item_id == "7227340"

            await client.close()

    # --- Error: 에러 조건 테스트 ---

    @pytest.mark.asyncio
    async def test_error_business_not_found(self):
        """
        [Error] 업체가 없을 때 None 반환
        """
        with patch.object(NaverGraphQLClient, '_execute_query', new_callable=AsyncMock) as mock_query:
            mock_query.return_value = {"business": None}

            client = NaverGraphQLClient()
            result = await client.fetch_business_info("999999999")

            assert result is None

            await client.close()

    @pytest.mark.asyncio
    async def test_error_biz_item_not_found(self, sample_biz_items_api_response):
        """
        [Error] 아이템이 없을 때 None 반환
        """
        with patch.object(NaverGraphQLClient, '_execute_query', new_callable=AsyncMock) as mock_query:
            mock_query.return_value = sample_biz_items_api_response["data"]

            client = NaverGraphQLClient()
            result = await client.fetch_biz_item("1543589", "999999999")

            assert result is None

            await client.close()

    @pytest.mark.asyncio
    async def test_error_empty_biz_items_list(self):
        """
        [Error] bizItems가 빈 배열일 때 빈 리스트 반환
        """
        with patch.object(NaverGraphQLClient, '_execute_query', new_callable=AsyncMock) as mock_query:
            mock_query.return_value = {"bizItems": []}

            client = NaverGraphQLClient()
            result = await client.fetch_biz_items("1543589")

            assert result == []

            await client.close()

    @pytest.mark.asyncio
    async def test_error_api_returns_none(self):
        """
        [Error] API가 None 반환 시 처리
        """
        with patch.object(NaverGraphQLClient, '_execute_query', new_callable=AsyncMock) as mock_query:
            mock_query.return_value = None

            client = NaverGraphQLClient()
            result = await client.fetch_business_info("1543589")

            assert result is None

            await client.close()

    # --- Boundary: 경계값 테스트 ---

    @pytest.mark.asyncio
    async def test_boundary_address_json_as_string(self):
        """
        [Boundary] addressJson이 문자열로 올 때 처리
        """
        response = {
            "data": {
                "business": {
                    "businessId": "123",
                    "name": "테스트",
                    "coordinates": [],
                    "addressJson": '{"roadAddr": "서울시"}',  # 문자열
                    "phoneInformationJson": None
                }
            }
        }

        with patch.object(NaverGraphQLClient, '_execute_query', new_callable=AsyncMock) as mock_query:
            mock_query.return_value = response["data"]

            client = NaverGraphQLClient()
            result = await client.fetch_business_info("123")

            assert result.road_address == "서울시"

            await client.close()

    @pytest.mark.asyncio
    async def test_boundary_coordinates_empty(self):
        """
        [Boundary] coordinates가 빈 배열일 때
        """
        response = {
            "data": {
                "business": {
                    "businessId": "123",
                    "name": "테스트",
                    "coordinates": [],
                    "addressJson": {},
                    "phoneInformationJson": {}
                }
            }
        }

        with patch.object(NaverGraphQLClient, '_execute_query', new_callable=AsyncMock) as mock_query:
            mock_query.return_value = response["data"]

            client = NaverGraphQLClient()
            result = await client.fetch_business_info("123")

            assert result.latitude is None
            assert result.longitude is None

            await client.close()

    # --- Existence: 존재 여부 ---

    def test_existence_graphql_endpoint(self):
        """
        [Existence] GraphQL 엔드포인트가 정의되어 있는지
        """
        assert NAVER_GRAPHQL_ENDPOINT is not None
        assert "graphql" in NAVER_GRAPHQL_ENDPOINT

    def test_existence_singleton_client(self):
        """
        [Existence] 싱글톤 클라이언트가 생성되는지
        """
        client = get_naver_graphql_client()
        assert client is not None
        assert isinstance(client, NaverGraphQLClient)

    # --- Cardinality: 개수 검증 ---

    @pytest.mark.asyncio
    async def test_cardinality_multiple_biz_items(self, sample_biz_items_api_response):
        """
        [Cardinality] 여러 아이템이 올바르게 파싱되는지
        """
        with patch.object(NaverGraphQLClient, '_execute_query', new_callable=AsyncMock) as mock_query:
            mock_query.return_value = sample_biz_items_api_response["data"]

            client = NaverGraphQLClient()
            result = await client.fetch_biz_items("1543589")

            assert len(result) == 2
            item_ids = [item.biz_item_id for item in result]
            assert "7227340" in item_ids
            assert "7227341" in item_ids

            await client.close()


# ============================================================
# 4. URL 파싱 및 임포트 통합 테스트
# ============================================================

class TestUrlImportIntegration:
    """URL 임포트 통합 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_url_parsing(self):
        """
        [Right] URL에서 올바른 정보가 추출되는지
        """
        from app.utils.parsers import parse_naver_booking_url

        url = "https://booking.naver.com/booking/6/bizes/1543589/items/7227340?startDateTime=2025-12-20"
        result = parse_naver_booking_url(url)

        assert result.is_valid
        assert result.business_id == "1543589"
        assert result.item_id == "7227340"
        assert result.category == "6"
        assert "2025-12-20" in result.start_date

    def test_right_url_with_business_type_id(self):
        """
        [Right] businessTypeId 쿼리 파라미터가 파싱되는지
        """
        from app.utils.parsers import parse_naver_booking_url

        url = "https://booking.naver.com/booking/6/bizes/1543589/items/7227340?startDateTime=2025-12-20&businessTypeId=6"
        result = parse_naver_booking_url(url)

        assert result.is_valid
        assert result.business_type_id == "6"

    # --- Error: 에러 조건 테스트 ---

    def test_error_invalid_url_format(self):
        """
        [Error] 잘못된 URL 형식 처리
        """
        from app.utils.parsers import parse_naver_booking_url

        url = "https://example.com/invalid/url"
        result = parse_naver_booking_url(url)

        assert not result.is_valid
        assert result.error is not None

    def test_error_missing_business_id(self):
        """
        [Error] business_id가 없는 URL 처리
        """
        from app.utils.parsers import parse_naver_booking_url

        url = "https://booking.naver.com/booking/6/items/7227340"
        result = parse_naver_booking_url(url)

        assert not result.is_valid

    # --- Conformance: 형식 준수 ---

    def test_conformance_date_extraction(self):
        """
        [Conformance] 날짜가 YYYY-MM-DD 형식으로 추출되는지
        """
        from app.utils.parsers import parse_naver_booking_url, extract_date_only

        url = "https://booking.naver.com/booking/6/bizes/1543589/items/7227340?startDateTime=2025-12-20T00:00:00%2B09:00"
        result = parse_naver_booking_url(url)
        date = extract_date_only(result.start_date)

        assert date == "2025-12-20"


# ============================================================
# 5. DualCheckResult 및 fetch_schedule_dual 테스트
# ============================================================

class TestDualCheckResult:
    """DualCheckResult 데이터클래스 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_dual_check_result_creation(self):
        """
        [Right] DualCheckResult가 올바르게 생성되는지
        """
        result = DualCheckResult(
            can_book=True,
            schedule=None,
            has_slots=True,
            http_ok=True,
            error_reason=None
        )

        assert result.can_book is True
        assert result.has_slots is True
        assert result.http_ok is True
        assert result.error_reason is None

    # --- Conformance: 형식 준수 ---

    def test_conformance_error_reason_values(self):
        """
        [Conformance] error_reason이 예상된 값만 가지는지
        """
        valid_reasons = ["graphql_failed", "no_slots", "http_302", None]

        for reason in valid_reasons:
            result = DualCheckResult(
                can_book=reason is None,
                schedule=None,
                has_slots=False,
                http_ok=True,
                error_reason=reason
            )
            assert result.error_reason in valid_reasons


class TestFetchScheduleDual:
    """fetch_schedule_dual 메서드 테스트"""

    @pytest.fixture
    def sample_schedule_info(self):
        """스케줄 정보 샘플"""
        slot = ScheduleSlot(
            slot_id="2025-12-13_10:00",
            start_time="2025-12-13 10:00:00",
            date="2025-12-13",
            time="10:00",
            is_business_day=True,
            is_sale_day=True,
            stock=5,
            unit_stock=5,
            unit_booking_count=0,
            duration=60,
            min_booking_count=1,
            max_booking_count=10,
            prices=[],
            raw_data={}
        )
        return ScheduleInfo(
            business_id="123",
            biz_item_id="456",
            available_dates=["2025-12-13"],
            slots=[slot],
            slots_by_date={"2025-12-13": [slot]},
            proxy_url=None
        )

    @pytest.fixture
    def empty_schedule_info(self):
        """빈 스케줄 정보 (슬롯 없음)"""
        return ScheduleInfo(
            business_id="123",
            biz_item_id="456",
            available_dates=[],
            slots=[],
            slots_by_date={},
            proxy_url=None
        )

    # --- Right: 결과가 올바른가? ---

    @pytest.mark.asyncio
    async def test_right_can_book_when_graphql_success_slots_exist_http_ok(self, sample_schedule_info):
        """
        [Right] GraphQL 성공 + 슬롯 있음 + HTTP OK → can_book=True
        """
        client = NaverGraphQLClient()

        with patch.object(client, 'fetch_schedule', new_callable=AsyncMock) as mock_graphql, \
             patch.object(client, 'fetch_schedule_http', new_callable=AsyncMock) as mock_http:

            mock_graphql.return_value = sample_schedule_info
            mock_http.return_value = sample_schedule_info  # HTTP도 성공

            result = await client.fetch_schedule_dual(
                business_type_id=5,
                business_id="123",
                biz_item_id="456",
                target_date="2025-12-13"
            )

            assert result.can_book is True
            assert result.has_slots is True
            assert result.http_ok is True
            assert result.error_reason is None
            assert result.schedule is not None

        await client.close()

    @pytest.mark.asyncio
    async def test_right_cannot_book_when_graphql_failed(self, sample_schedule_info):
        """
        [Right] GraphQL 실패 → can_book=False, error_reason="graphql_failed"
        """
        client = NaverGraphQLClient()

        with patch.object(client, 'fetch_schedule', new_callable=AsyncMock) as mock_graphql, \
             patch.object(client, 'fetch_schedule_http', new_callable=AsyncMock) as mock_http:

            mock_graphql.return_value = None  # GraphQL 실패
            mock_http.return_value = sample_schedule_info

            result = await client.fetch_schedule_dual(
                business_type_id=5,
                business_id="123",
                biz_item_id="456",
                target_date="2025-12-13"
            )

            assert result.can_book is False
            assert result.error_reason == "graphql_failed"
            assert result.schedule is None

        await client.close()

    @pytest.mark.asyncio
    async def test_right_cannot_book_when_no_slots(self, empty_schedule_info):
        """
        [Right] GraphQL 성공 + 슬롯 없음 → can_book=False, error_reason="no_slots"
        """
        client = NaverGraphQLClient()

        with patch.object(client, 'fetch_schedule', new_callable=AsyncMock) as mock_graphql, \
             patch.object(client, 'fetch_schedule_http', new_callable=AsyncMock) as mock_http:

            mock_graphql.return_value = empty_schedule_info  # 슬롯 없음
            mock_http.return_value = empty_schedule_info

            result = await client.fetch_schedule_dual(
                business_type_id=5,
                business_id="123",
                biz_item_id="456",
                target_date="2025-12-13"
            )

            assert result.can_book is False
            assert result.has_slots is False
            assert result.error_reason == "no_slots"

        await client.close()

    @pytest.mark.asyncio
    async def test_right_cannot_book_when_http_302(self, sample_schedule_info):
        """
        [Right] GraphQL 성공 + 슬롯 있음 + HTTP 302 → can_book=False, error_reason="http_302"
        """
        client = NaverGraphQLClient()

        with patch.object(client, 'fetch_schedule', new_callable=AsyncMock) as mock_graphql, \
             patch.object(client, 'fetch_schedule_http', new_callable=AsyncMock) as mock_http:

            mock_graphql.return_value = sample_schedule_info  # GraphQL 성공
            mock_http.return_value = None  # HTTP 302 (실패)

            result = await client.fetch_schedule_dual(
                business_type_id=5,
                business_id="123",
                biz_item_id="456",
                target_date="2025-12-13"
            )

            assert result.can_book is False
            assert result.has_slots is True
            assert result.http_ok is False
            assert result.error_reason == "http_302"

        await client.close()

    # --- Boundary: 경계값 테스트 ---

    @pytest.mark.asyncio
    async def test_boundary_slots_exist_but_no_available_dates(self):
        """
        [Boundary] 슬롯은 있지만 available_dates가 비어있는 경우
        """
        slot = ScheduleSlot(
            slot_id="test", start_time="2025-12-13 10:00:00",
            date="2025-12-13", time="10:00", is_business_day=True,
            is_sale_day=False,  # 판매 불가
            stock=0, unit_stock=0, unit_booking_count=0,
            duration=60, min_booking_count=1, max_booking_count=10,
            prices=[], raw_data={}
        )
        schedule = ScheduleInfo(
            business_id="123", biz_item_id="456",
            available_dates=[],  # 예약 가능 날짜 없음
            slots=[slot],
            slots_by_date={"2025-12-13": [slot]},
            proxy_url=None
        )

        client = NaverGraphQLClient()

        with patch.object(client, 'fetch_schedule', new_callable=AsyncMock) as mock_graphql, \
             patch.object(client, 'fetch_schedule_http', new_callable=AsyncMock) as mock_http:

            mock_graphql.return_value = schedule
            mock_http.return_value = schedule

            result = await client.fetch_schedule_dual(
                business_type_id=5,
                business_id="123",
                biz_item_id="456",
                target_date="2025-12-13"
            )

            # slots > 0 but available_dates == 0 → has_slots = False
            assert result.can_book is False
            assert result.has_slots is False
            assert result.error_reason == "no_slots"

        await client.close()

    # --- Error: 에러 조건 테스트 ---

    @pytest.mark.asyncio
    async def test_error_graphql_exception(self, sample_schedule_info):
        """
        [Error] GraphQL에서 예외 발생 시 처리
        """
        client = NaverGraphQLClient()

        with patch.object(client, 'fetch_schedule', new_callable=AsyncMock) as mock_graphql, \
             patch.object(client, 'fetch_schedule_http', new_callable=AsyncMock) as mock_http:

            mock_graphql.side_effect = Exception("GraphQL Error")
            mock_http.return_value = sample_schedule_info

            result = await client.fetch_schedule_dual(
                business_type_id=5,
                business_id="123",
                biz_item_id="456",
                target_date="2025-12-13"
            )

            assert result.can_book is False
            assert result.error_reason == "graphql_failed"

        await client.close()

    @pytest.mark.asyncio
    async def test_error_http_exception(self, sample_schedule_info):
        """
        [Error] HTTP에서 예외 발생 시 처리 (http_ok=False)
        """
        client = NaverGraphQLClient()

        with patch.object(client, 'fetch_schedule', new_callable=AsyncMock) as mock_graphql, \
             patch.object(client, 'fetch_schedule_http', new_callable=AsyncMock) as mock_http:

            mock_graphql.return_value = sample_schedule_info
            mock_http.side_effect = Exception("HTTP Error")

            result = await client.fetch_schedule_dual(
                business_type_id=5,
                business_id="123",
                biz_item_id="456",
                target_date="2025-12-13"
            )

            assert result.can_book is False
            assert result.http_ok is False
            assert result.error_reason == "http_302"

        await client.close()

    # --- Cross-check: 교차 검증 ---

    @pytest.mark.asyncio
    async def test_cross_check_both_methods_called_concurrently(self, sample_schedule_info):
        """
        [Cross-check] GraphQL과 HTTP가 동시에 호출되는지
        """
        client = NaverGraphQLClient()
        call_times = []

        async def mock_graphql(*args, **kwargs):
            call_times.append(("graphql", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.1)
            return sample_schedule_info

        async def mock_http(*args, **kwargs):
            call_times.append(("http", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.1)
            return sample_schedule_info

        with patch.object(client, 'fetch_schedule', side_effect=mock_graphql), \
             patch.object(client, 'fetch_schedule_http', side_effect=mock_http):

            await client.fetch_schedule_dual(
                business_type_id=5,
                business_id="123",
                biz_item_id="456",
                target_date="2025-12-13"
            )

            # 두 메서드 모두 호출됨
            assert len(call_times) == 2

            # 거의 동시에 호출됨 (차이 0.05초 미만)
            time_diff = abs(call_times[0][1] - call_times[1][1])
            assert time_diff < 0.05, f"동시 호출 아님: {time_diff}초 차이"

        await client.close()

    # --- Cardinality: 개수 검증 ---

    @pytest.mark.asyncio
    async def test_cardinality_schedule_slots_preserved(self, sample_schedule_info):
        """
        [Cardinality] 반환된 schedule의 슬롯 개수가 보존되는지
        """
        client = NaverGraphQLClient()

        with patch.object(client, 'fetch_schedule', new_callable=AsyncMock) as mock_graphql, \
             patch.object(client, 'fetch_schedule_http', new_callable=AsyncMock) as mock_http:

            mock_graphql.return_value = sample_schedule_info
            mock_http.return_value = sample_schedule_info

            result = await client.fetch_schedule_dual(
                business_type_id=5,
                business_id="123",
                biz_item_id="456",
                target_date="2025-12-13"
            )

            assert result.schedule is not None
            assert len(result.schedule.slots) == len(sample_schedule_info.slots)

        await client.close()


# ============================================================
# 6. 데이터 모델 확장 테스트
# ============================================================

class TestDataModelExtension:
    """데이터 모델 확장 테스트 (REQ-DATA-004)"""

    # --- Reference: 참조 검증 ---

    def test_reference_business_new_fields(self):
        """
        [Reference] Business 모델에 새 필드가 추가되었는지
        """
        from app.models.business import Business

        # 새로 추가된 필드 확인
        new_fields = [
            "place_id",
            "service_name",
            "road_address",
            "jibun_address",
            "detail_address",
            "latitude",
            "longitude",
            "phone",
            "api_synced_at"
        ]

        for field in new_fields:
            assert hasattr(Business, field), f"Business 모델에 {field} 필드가 없습니다"

    def test_reference_biz_item_new_fields(self):
        """
        [Reference] BizItem 모델에 새 필드가 추가되었는지
        """
        from app.models.biz_item import BizItem

        # 새로 추가된 필드 확인 (GraphQL API + 다중 프로필 통합)
        new_fields = [
            "description",
            "biz_item_type",
            "biz_item_sub_type",
            "booking_count_type",
            "min_booking_count",
            "max_booking_count",
            "start_date",
            "end_date",
            "extra_desc_json",
            "booking_precaution_json",
            "api_synced_at",
            "account_id",  # 다중 프로필 지원
        ]

        for field in new_fields:
            assert hasattr(BizItem, field), f"BizItem 모델에 {field} 필드가 없습니다"

    def test_reference_biz_item_account_relationship(self):
        """
        [Reference] BizItem과 Account 관계가 설정되었는지
        """
        from app.models.biz_item import BizItem

        assert hasattr(BizItem, "account"), "BizItem 모델에 account 관계가 없습니다"
        assert hasattr(BizItem, "account_id"), "BizItem 모델에 account_id 필드가 없습니다"

    # --- Conformance: 형식 준수 ---

    def test_conformance_schema_fields(self):
        """
        [Conformance] Pydantic 스키마에 새 필드가 추가되었는지
        """
        from app.schemas.business import BusinessBase, BusinessUpdate

        business_base_fields = BusinessBase.model_fields
        assert "place_id" in business_base_fields
        assert "service_name" in business_base_fields
        assert "road_address" in business_base_fields
        assert "latitude" in business_base_fields
        assert "longitude" in business_base_fields

        business_update_fields = BusinessUpdate.model_fields
        assert "place_id" in business_update_fields
        assert "service_name" in business_update_fields

    def test_conformance_biz_item_schema_fields(self):
        """
        [Conformance] BizItem Pydantic 스키마에 새 필드가 추가되었는지
        """
        from app.schemas.biz_item import BizItemBase, BizItemUpdate

        base_fields = BizItemBase.model_fields
        assert "description" in base_fields
        assert "biz_item_type" in base_fields
        assert "min_booking_count" in base_fields
        assert "max_booking_count" in base_fields

        update_fields = BizItemUpdate.model_fields
        assert "description" in update_fields
        assert "biz_item_type" in update_fields


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
