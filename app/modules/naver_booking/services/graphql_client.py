"""
NaverGraphQLClient - 네이버 예약 GraphQL API 클라이언트
작성일: 2025-12-03
요구사항: REQ-DATA-004 (업체/상품 상세정보 조회)

네이버 예약 GraphQL API를 통해 업체(Business) 및 상품(BizItem) 정보를 조회합니다.

Rate Limiting (2025-12-11):
- Semaphore로 동시 요청 제한 (MAX_CONCURRENT_GRAPHQL_REQUESTS)
- TTL 캐시로 동일 요청 중복 방지 (GRAPHQL_CACHE_TTL)

Proxy Support (2025-12-11):
- ProxyManager를 통한 프록시 로테이션 지원
- HTTP 403/429 에러 시 자동 프록시 교체
"""
import aiohttp
import asyncio
import json
import time
import hashlib
import re
from typing import Dict, Any, Optional, List, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from app.config import logger, settings
from app.utils.slot_utils import is_slot_available_from_dict, is_slot_available_from_obj

if TYPE_CHECKING:
    from app.services.proxy_manager import ProxyManager

# Proxy usage logger (optional)
try:
    from app.services.proxy_usage_logger import get_proxy_usage_logger
    _proxy_usage_logger = get_proxy_usage_logger()
except ImportError:
    _proxy_usage_logger = None


# GraphQL 엔드포인트
NAVER_GRAPHQL_ENDPOINT = "https://m.booking.naver.com/graphql"

# 프록시 요청 타임아웃 (초) - 느린 프록시 감지용
# 1초 초과 시 타임아웃 → 다른 프록시로 재시도
PROXY_REQUEST_TIMEOUT = 1.0

# 직접 연결 타임아웃 (초) - 프록시 없이 연결 시
DIRECT_REQUEST_TIMEOUT = 30.0

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
    # 프록시 정보 (2025-12-11 추가)
    proxy_url: Optional[str] = None  # 사용한 프록시 URL
    # GraphQL 원본 응답 (2025-12-16 추가)
    raw_response: Optional[Dict[str, Any]] = None  # GraphQL API 원본 응답 데이터
    # 타이밍 상세 (2025-12-16 추가)
    retry_count: int = 0  # 프록시 재시도 횟수


@dataclass
class CacheEntry:
    """캐시 엔트리"""
    data: Any
    expires_at: float


@dataclass
class DualCheckResult:
    """GraphQL + 페이지 활성 동시 체크 결과"""
    can_book: bool  # 예약 가능 여부 (최종 판단)
    schedule: Optional[ScheduleInfo]  # GraphQL 스케줄 결과
    has_slots: bool  # 슬롯 존재 여부
    http_ok: bool  # 상품 활성 여부 (True면 활성, False면 비활성화 또는 확인 실패)
    http_checked: bool  # 페이지 체크 성공 여부 (True면 활성/비활성 확인됨)
    error_reason: Optional[str]  # 실패 사유: "graphql_failed", "no_slots", "inactive", "page_check_failed"


class NaverGraphQLClient:
    """네이버 예약 GraphQL API 클라이언트

    Rate Limiting:
    - _semaphore: 동시 요청 제한 (MAX_CONCURRENT_GRAPHQL_REQUESTS)
    - _cache: TTL 캐시 (GRAPHQL_CACHE_TTL초)
    """

    # 클래스 레벨 Semaphore 및 캐시 (모든 인스턴스 공유)
    _semaphore: Optional[asyncio.Semaphore] = None
    _cache: Dict[str, CacheEntry] = {}
    _last_cleanup: float = 0
    _cleanup_interval: int = 60  # 캐시 정리 간격 (초)

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        """Semaphore 싱글톤 반환"""
        if cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_GRAPHQL_REQUESTS)
            logger.info(f"[NaverGraphQL] Semaphore 초기화: 최대 {settings.MAX_CONCURRENT_GRAPHQL_REQUESTS}개 동시 요청")
        return cls._semaphore

    @classmethod
    def _get_cache_key(cls, operation: str, variables: Dict) -> str:
        """캐시 키 생성"""
        key_str = f"{operation}:{json.dumps(variables, sort_keys=True)}"
        return hashlib.md5(key_str.encode()).hexdigest()

    @classmethod
    def _get_from_cache(cls, key: str) -> Optional[Any]:
        """캐시에서 조회 (만료된 항목은 None 반환)"""
        if key in cls._cache:
            entry = cls._cache[key]
            if time.time() < entry.expires_at:
                return entry.data
            else:
                del cls._cache[key]
        return None

    @classmethod
    def _set_cache(cls, key: str, data: Any):
        """캐시에 저장"""
        cls._cache[key] = CacheEntry(
            data=data,
            expires_at=time.time() + settings.GRAPHQL_CACHE_TTL
        )

    @classmethod
    def _cleanup_expired_cache(cls):
        """만료된 캐시 항목 정리 (주기적)"""
        current_time = time.time()
        if current_time - cls._last_cleanup < cls._cleanup_interval:
            return

        cls._last_cleanup = current_time
        expired_keys = [
            key for key, entry in cls._cache.items()
            if current_time >= entry.expires_at
        ]
        for key in expired_keys:
            del cls._cache[key]

        if expired_keys:
            logger.debug(f"[NaverGraphQL] 만료된 캐시 {len(expired_keys)}개 정리됨")

    @classmethod
    def get_cache_stats(cls) -> Dict[str, Any]:
        """캐시 통계 반환 (디버그용)"""
        current_time = time.time()
        valid_count = sum(1 for entry in cls._cache.values() if current_time < entry.expires_at)
        return {
            "total_entries": len(cls._cache),
            "valid_entries": valid_count,
            "expired_entries": len(cls._cache) - valid_count,
            "cache_ttl": settings.GRAPHQL_CACHE_TTL
        }

    @classmethod
    def clear_cache(cls):
        """캐시 전체 삭제"""
        cls._cache.clear()
        logger.info("[NaverGraphQL] 캐시 전체 삭제됨")

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

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        proxy_manager: Optional["ProxyManager"] = None
    ):
        """
        Args:
            session: aiohttp 세션 (없으면 자동 생성)
            proxy_manager: 프록시 매니저 (없으면 프록시 미사용)
        """
        self._session = session
        self._own_session = session is None
        self._proxy_manager = proxy_manager
        self._last_used_proxy: Optional[str] = None  # 마지막 사용한 프록시 URL
        self._last_retry_count: int = 0  # 마지막 요청의 재시도 횟수

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
        operation_name: str,
        use_cache: bool = True,
        schedule_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        GraphQL 쿼리를 실행합니다.

        Rate Limiting:
        - 캐시 확인 후 히트 시 즉시 반환
        - Semaphore로 동시 요청 제한
        - 성공 시 캐시에 저장

        Args:
            query: GraphQL 쿼리 문자열
            variables: 쿼리 변수
            operation_name: 오퍼레이션 이름
            use_cache: 캐시 사용 여부 (기본: True)

        Returns:
            Dict: API 응답 데이터 또는 None
        """
        # 주기적 캐시 정리
        self._cleanup_expired_cache()

        # 캐시 확인
        cache_key = self._get_cache_key(operation_name, variables)
        if use_cache:
            cached = self._get_from_cache(cache_key)
            if cached is not None:
                logger.debug(f"[NaverGraphQL] 캐시 히트: {operation_name}")
                return cached

        # Semaphore로 동시 요청 제한
        semaphore = self._get_semaphore()
        async with semaphore:
            # Semaphore 획득 후 다시 캐시 확인 (대기 중 다른 요청이 캐시에 저장했을 수 있음)
            if use_cache:
                cached = self._get_from_cache(cache_key)
                if cached is not None:
                    logger.debug(f"[NaverGraphQL] 캐시 히트 (대기 후): {operation_name}")
                    return cached

            # 실제 API 호출
            result = await self._do_execute_query(query, variables, operation_name, schedule_id=schedule_id)

            # 성공 시 캐시에 저장
            if result is not None and use_cache:
                self._set_cache(cache_key, result)

            return result

    async def _do_execute_query(
        self,
        query: str,
        variables: Dict[str, Any],
        operation_name: str,
        max_retries: int = 10,
        schedule_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """실제 GraphQL 쿼리 실행 (내부용)

        Args:
            query: GraphQL 쿼리
            variables: 쿼리 변수
            operation_name: 오퍼레이션 이름
            max_retries: 프록시 실패 시 최대 재시도 횟수 (기본: 10)
            schedule_id: 모니터링 스케줄 ID (프록시 사용 이력 추적용)
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

        last_error = None
        tried_proxies: set = set()  # 이미 시도한 프록시 추적

        # 프록시 사용 이력 추적 시작
        usage_request_id = None
        if _proxy_usage_logger and schedule_id:
            usage_request_id = _proxy_usage_logger.start_request(
                schedule_id=schedule_id,
                target_url=f"{NAVER_GRAPHQL_ENDPOINT}?opName={operation_name}",
                fetch_method="graphql_api"
            )

        for attempt in range(max_retries + 1):
            # 프록시 URL 가져오기
            proxy_url = None
            if self._proxy_manager and self._proxy_manager.is_available:
                proxy_url = self._proxy_manager.get_fresh_proxy(exclude=tried_proxies)
                if proxy_url:
                    tried_proxies.add(proxy_url)
                if attempt == 0:
                    logger.debug(f"[NaverGraphQL] 프록시 사용: {proxy_url}")
                else:
                    logger.info(f"[NaverGraphQL] 재시도 #{attempt}/{max_retries} - 프록시: {proxy_url}")

            # 마지막 사용한 프록시 저장 (추적용)
            self._last_used_proxy = proxy_url

            # 타임아웃 설정: 프록시 사용 시 1초, 직접 연결 시 30초
            request_timeout = PROXY_REQUEST_TIMEOUT if proxy_url else DIRECT_REQUEST_TIMEOUT

            # 응답 시간 측정 시작
            request_start_time = time.time()

            try:
                async with session.post(
                    f"{NAVER_GRAPHQL_ENDPOINT}?opName={operation_name}",
                    headers=headers,
                    json=payload,
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=request_timeout)
                ) as response:
                    # 응답 시간 계산
                    response_time = time.time() - request_start_time

                    # 302 리다이렉트 - 실패 처리 (봇 탐지 등)
                    if response.status == 302:
                        logger.warning(f"[NaverGraphQL] HTTP 302 리다이렉트 감지 - 실패 처리")
                        return None

                    # 프록시 관련 에러 처리 - 재시도
                    if response.status in (403, 429) and proxy_url and self._proxy_manager:
                        logger.warning(
                            f"[NaverGraphQL] HTTP {response.status} - 프록시 실패: {proxy_url}"
                        )
                        self._proxy_manager.mark_failed(proxy_url, f"HTTP {response.status}")
                        last_error = f"HTTP {response.status}"
                        # 프록시 사용 이력 기록 (실패)
                        if usage_request_id and proxy_url:
                            _proxy_usage_logger.log_attempt(
                                request_id=usage_request_id,
                                proxy_url=proxy_url,
                                success=False,
                                http_status=response.status,
                                error_type=f"http_{response.status}",
                                response_time_ms=int(response_time * 1000)
                            )
                        continue  # 다음 프록시로 재시도

                    if response.status != 200:
                        logger.error(f"[NaverGraphQL] HTTP {response.status} for {operation_name}")
                        # 프록시 사용 이력 기록 (실패 - 프록시 문제 아님)
                        if usage_request_id and proxy_url:
                            _proxy_usage_logger.log_attempt(
                                request_id=usage_request_id,
                                proxy_url=proxy_url,
                                success=False,
                                http_status=response.status,
                                error_type=f"http_{response.status}",
                                response_time_ms=int(response_time * 1000)
                            )
                            _proxy_usage_logger.complete_request(usage_request_id)
                        return None  # 프록시 문제가 아닌 에러는 재시도하지 않음

                    data = await response.json()

                    if "errors" in data and data["errors"]:
                        logger.error(f"[NaverGraphQL] GraphQL errors: {data['errors']}")
                        # 프록시 사용 이력 기록 (실패 - GraphQL 에러)
                        if usage_request_id and proxy_url:
                            _proxy_usage_logger.log_attempt(
                                request_id=usage_request_id,
                                proxy_url=proxy_url,
                                success=False,
                                http_status=200,
                                error_type="graphql_error",
                                response_time_ms=int(response_time * 1000)
                            )
                            _proxy_usage_logger.complete_request(usage_request_id)
                        return None

                    # 성공 로깅
                    if proxy_url:
                        logger.debug(f"[NaverGraphQL] 성공 - 프록시: {proxy_url}, 응답시간: {response_time:.2f}s")

                    # 프록시 사용 이력 기록 (성공) - log_attempt이 성공 시 자동으로 complete 처리
                    if usage_request_id and proxy_url:
                        _proxy_usage_logger.log_attempt(
                            request_id=usage_request_id,
                            proxy_url=proxy_url,
                            success=True,
                            http_status=200,
                            response_time_ms=int(response_time * 1000)
                        )

                    # 재시도 횟수 저장 (attempt는 0부터 시작하므로 실제 재시도 횟수)
                    self._last_retry_count = attempt
                    return data.get("data")

            except asyncio.TimeoutError:
                # 타임아웃 = 느린 프록시 → mark_slow() 호출 + 재시도
                response_time = time.time() - request_start_time
                if proxy_url and self._proxy_manager:
                    logger.warning(
                        f"[NaverGraphQL] 프록시 타임아웃 ({response_time:.1f}s > {request_timeout}s): {proxy_url}"
                    )
                    self._proxy_manager.mark_slow(proxy_url, response_time)
                    last_error = f"timeout:{response_time:.1f}s"
                    # 프록시 사용 이력 기록 (실패 - 타임아웃)
                    if usage_request_id and proxy_url:
                        _proxy_usage_logger.log_attempt(
                            request_id=usage_request_id,
                            proxy_url=proxy_url,
                            success=False,
                            error_type="timeout",
                            response_time_ms=int(response_time * 1000)
                        )
                    continue  # 다른 프록시로 재시도
                else:
                    # 직접 연결 타임아웃은 재시도하지 않음
                    logger.error(f"[NaverGraphQL] 직접 연결 타임아웃 for {operation_name}")
                    if usage_request_id:
                        _proxy_usage_logger.complete_request(usage_request_id)
                    return None

            except aiohttp.ClientError as e:
                # 프록시 연결 실패 시 블랙리스트 등록 후 재시도
                response_time = time.time() - request_start_time
                if proxy_url and self._proxy_manager:
                    self._proxy_manager.mark_failed(proxy_url, str(e)[:50])
                logger.error(f"[NaverGraphQL] Request error for {operation_name}: {e}")
                last_error = str(e)[:50]
                # 프록시 사용 이력 기록 (실패 - 연결 에러)
                if usage_request_id and proxy_url:
                    _proxy_usage_logger.log_attempt(
                        request_id=usage_request_id,
                        proxy_url=proxy_url,
                        success=False,
                        error_type="connection_error",
                        error_message=str(e)[:200],
                        response_time_ms=int(response_time * 1000)
                    )
                continue  # 다음 프록시로 재시도

            except json.JSONDecodeError as e:
                logger.error(f"[NaverGraphQL] JSON decode error for {operation_name}: {e}")
                if usage_request_id:
                    _proxy_usage_logger.complete_request(usage_request_id)
                return None  # JSON 에러는 재시도하지 않음

        # 모든 프록시 재시도 실패 → 직접 연결로 폴백
        if self._proxy_manager and tried_proxies:
            logger.info(f"[NaverGraphQL] 프록시 {len(tried_proxies)}개 모두 실패 → 직접 연결 시도")
            fallback_start_time = time.time()
            try:
                async with session.post(
                    f"{NAVER_GRAPHQL_ENDPOINT}?opName={operation_name}",
                    headers=headers,
                    json=payload,
                    proxy=None,
                    timeout=aiohttp.ClientTimeout(total=DIRECT_REQUEST_TIMEOUT)
                ) as response:
                    fallback_response_time = time.time() - fallback_start_time
                    if response.status == 200:
                        data = await response.json()
                        if "errors" not in data or not data["errors"]:
                            logger.info(f"[NaverGraphQL] 직접 연결 성공")
                            # 프록시 실패 후 직접 연결 성공: 재시도 횟수 = 프록시 시도 수
                            self._last_retry_count = len(tried_proxies)
                            # 직접 연결 성공 로깅 (proxy_url=None으로 direct connection 표시)
                            if usage_request_id:
                                _proxy_usage_logger.log_attempt(
                                    request_id=usage_request_id,
                                    proxy_url="direct",
                                    success=True,
                                    http_status=200,
                                    response_time_ms=int(fallback_response_time * 1000)
                                )
                            return data.get("data")
            except Exception as e:
                logger.error(f"[NaverGraphQL] 직접 연결도 실패: {e}")

        # 최종 실패 - 로깅 완료 처리
        if usage_request_id:
            _proxy_usage_logger.complete_request(usage_request_id)
        logger.error(f"[NaverGraphQL] {operation_name} 모든 재시도 실패 ({max_retries}회) - 마지막 에러: {last_error}")
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
            if extra_desc is not None and not isinstance(extra_desc, str):
                extra_desc = json.dumps(extra_desc, ensure_ascii=False)

            booking_precaution = item.get("bookingPrecautionJson")
            if booking_precaution is not None and not isinstance(booking_precaution, str):
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
        days_ahead: int = 35,
        schedule_id: Optional[int] = None
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
            schedule_id: 모니터링 스케줄 ID (프록시 사용 이력 추적용)

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

        data = await self._execute_query(self.SCHEDULE_QUERY, variables, "schedule", schedule_id=schedule_id)
        # 이 호출에 사용된 프록시 URL 및 재시도 횟수 저장
        used_proxy = self._last_used_proxy
        retry_count = self._last_retry_count

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
                slots_by_date={},
                proxy_url=used_proxy,
                raw_response=data,
                retry_count=retry_count
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

            # 예약 가능 여부 체크
            # stock > 0 AND (unit_stock - unit_booking_count) > 0 AND is_sale_day
            stock_value = slot_data.get("stock") or 0
            is_available = is_slot_available_from_dict(slot_data)

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
            slots_by_date=slots_by_date,
            proxy_url=used_proxy,
            raw_response=data,
            retry_count=retry_count
        )

    def _check_page_active(self, html_content: str) -> bool:
        """
        HTML 페이지 내용에서 상품 활성화 상태를 확인합니다.

        비활성화 판단 기준:
        - __APOLLO_STATE__.ROOT_QUERY에 'placeProfile' 또는 'account' 키가 없으면 비활성화

        Args:
            html_content: HTML 페이지 내용

        Returns:
            bool: True면 활성, False면 비활성화
        """
        try:
            # __APOLLO_STATE__ 추출
            apollo_match = re.search(r'window\.__APOLLO_STATE__\s*=\s*(\{[^<]*\})', html_content)
            if not apollo_match:
                logger.warning("[PageCheck] __APOLLO_STATE__ not found")
                return True  # 파싱 실패 시 활성으로 간주 (GraphQL 결과에 의존)

            apollo_state = json.loads(apollo_match.group(1))
            root_query = apollo_state.get('ROOT_QUERY', {})

            # ROOT_QUERY 키 확인 - placeProfile 또는 account가 있으면 활성
            has_place_profile = any('placeProfile' in key for key in root_query.keys())
            has_account = any('account' in key for key in root_query.keys())

            if has_place_profile or has_account:
                logger.debug(f"[PageCheck] 활성 (placeProfile={has_place_profile}, account={has_account})")
                return True
            else:
                logger.info(f"[PageCheck] 비활성화 감지 (ROOT_QUERY keys: {list(root_query.keys())})")
                return False

        except json.JSONDecodeError as e:
            logger.warning(f"[PageCheck] JSON 파싱 실패: {e}")
            return True  # 파싱 실패 시 활성으로 간주

    async def check_product_active(
        self,
        business_type_id: int,
        business_id: str,
        biz_item_id: str,
        target_date: str,
        max_retries: int = 3
    ) -> bool:
        """
        HTTP 요청으로 상품 활성 상태를 체크합니다.

        체크 방법:
        - 페이지 HTML의 __APOLLO_STATE__ 파싱
        - ROOT_QUERY에 placeProfile/account 키 존재 여부로 활성 판단

        Args:
            business_type_id: 업체 타입 ID
            business_id: 업체 ID
            biz_item_id: 상품 ID
            target_date: 대상 날짜 (YYYY-MM-DD)
            max_retries: 최대 재시도 횟수

        Returns:
            bool: True면 활성, False면 비활성화, None이면 확인 불가
        """
        session = await self._ensure_session()

        # 네이버 예약 페이지 URL
        url = (
            f"https://m.booking.naver.com/booking/{business_type_id}/bizes/"
            f"{business_id}/items/{biz_item_id}?startDateTime={target_date}"
        )

        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "user-agent": DEFAULT_USER_AGENT,
            "referer": "https://m.booking.naver.com/",
        }

        last_error = None
        tried_proxies: set = set()

        for attempt in range(max_retries + 1):
            # 프록시 URL 가져오기
            proxy_url = None
            if self._proxy_manager and self._proxy_manager.is_available:
                proxy_url = self._proxy_manager.get_fresh_proxy(exclude=tried_proxies)
                if proxy_url:
                    tried_proxies.add(proxy_url)
                if attempt > 0:
                    logger.debug(f"[PageActive] 재시도 #{attempt}/{max_retries} - 프록시: {proxy_url}")

            try:
                async with session.get(
                    url,
                    headers=headers,
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                    allow_redirects=False
                ) as response:
                    logger.debug(f"[PageActive] status={response.status} | proxy={'Y' if proxy_url else 'N'}")

                    # 200 OK - 페이지 내용 확인
                    if response.status == 200:
                        html_content = await response.text()
                        is_active = self._check_page_active(html_content)
                        if is_active:
                            logger.debug(f"[PageActive] 활성 상품")
                            return True
                        else:
                            logger.info(f"[PageActive] 비활성화 감지")
                            return False

                    # 302 - 비활성화 (fallback)
                    if response.status == 302:
                        logger.info(f"[PageActive] 302 redirect - 비활성화")
                        return False

                    # 403/429 - 프록시 실패로 재시도
                    if response.status in (403, 429):
                        if proxy_url and self._proxy_manager:
                            self._proxy_manager.mark_failed(proxy_url, f"HTTP {response.status}")
                        last_error = f"HTTP {response.status}"
                        continue

                    # 기타 에러 - 재시도
                    logger.warning(f"[PageActive] HTTP {response.status} - 재시도")
                    last_error = f"HTTP {response.status}"
                    continue

            except asyncio.TimeoutError:
                if proxy_url and self._proxy_manager:
                    self._proxy_manager.mark_failed(proxy_url, "timeout")
                last_error = "timeout"
                continue

            except aiohttp.ClientError as e:
                if proxy_url and self._proxy_manager:
                    self._proxy_manager.mark_failed(proxy_url, str(e)[:30])
                last_error = str(e)[:30]
                continue

        # 모든 프록시 재시도 실패 - 프록시 없이 직접 연결 시도
        if self._proxy_manager and tried_proxies:
            logger.info(f"[PageActive] 프록시 {len(tried_proxies)}개 모두 실패 → 직접 연결 시도")
            try:
                async with session.get(
                    url,
                    headers=headers,
                    proxy=None,
                    timeout=aiohttp.ClientTimeout(total=10),
                    allow_redirects=False
                ) as response:
                    if response.status == 200:
                        html_content = await response.text()
                        is_active = self._check_page_active(html_content)
                        if is_active:
                            logger.info(f"[PageActive] 직접 연결: 활성")
                            return True
                        else:
                            logger.info(f"[PageActive] 직접 연결: 비활성화")
                            return False
                    if response.status == 302:
                        logger.info(f"[PageActive] 직접 연결: 302 - 비활성화")
                        return False
                    logger.warning(f"[PageActive] 직접 연결: HTTP {response.status}")
            except asyncio.TimeoutError:
                logger.warning(f"[PageActive] 직접 연결: timeout")
            except aiohttp.ClientError as e:
                logger.warning(f"[PageActive] 직접 연결: {e}")

        # 최종 실패 - None 반환 (확인 불가)
        logger.warning(f"[PageActive] 모든 재시도 실패 - 확인 불가")
        return None

    async def fetch_schedule_dual(
        self,
        business_type_id: int,
        business_id: str,
        biz_item_id: str,
        target_date: str,
        days_ahead: int = 1,
        schedule_id: Optional[int] = None
    ) -> DualCheckResult:
        """
        GraphQL과 페이지 활성 체크를 동시에 실행하여 예약 가능 여부를 판단합니다.

        예약 가능 조건:
        - GraphQL 성공 AND 슬롯 있음 AND 상품 활성

        Args:
            business_type_id: 업체 타입 ID
            business_id: 업체 ID
            biz_item_id: 상품 ID
            target_date: 대상 날짜 (YYYY-MM-DD)
            days_ahead: 조회 기간 (GraphQL용)
            schedule_id: 모니터링 스케줄 ID (프록시 사용 이력 추적용)

        Returns:
            DualCheckResult: 체크 결과
        """
        # GraphQL과 페이지 활성 체크를 동시에 실행
        graphql_task = asyncio.create_task(
            self.fetch_schedule(
                business_type_id=business_type_id,
                business_id=business_id,
                biz_item_id=biz_item_id,
                start_date=target_date,
                days_ahead=days_ahead,
                schedule_id=schedule_id
            )
        )

        page_task = asyncio.create_task(
            self.check_product_active(
                business_type_id=business_type_id,
                business_id=business_id,
                biz_item_id=biz_item_id,
                target_date=target_date
            )
        )

        # 둘 다 완료될 때까지 대기
        graphql_result, page_result = await asyncio.gather(
            graphql_task, page_task, return_exceptions=True
        )

        # 예외 처리
        if isinstance(graphql_result, Exception):
            logger.error(f"[NaverGraphQL] GraphQL 예외: {graphql_result}")
            graphql_result = None
        if isinstance(page_result, Exception):
            logger.error(f"[PageActive] 예외: {page_result}")
            page_result = None  # 예외 시 확인 실패

        # 페이지 결과 해석
        # page_result: True=활성, False=비활성화, None=확인 실패
        http_ok = page_result is True  # True일 때만 OK
        http_checked = page_result is not None  # None이 아니면 체크 성공

        # 1. GraphQL 실패 → 전체 실패
        if graphql_result is None:
            logger.warning(f"[NaverDual] GraphQL 실패 - 예약 불가")
            return DualCheckResult(
                can_book=False,
                schedule=None,
                has_slots=False,
                http_ok=http_ok,
                http_checked=http_checked,
                error_reason="graphql_failed"
            )

        # 2. 슬롯 확인 (stock > 0 AND remaining > 0 AND is_sale_day인 슬롯만 카운트)
        available_slots = [s for s in graphql_result.slots if is_slot_available_from_obj(s)]
        total_slots = len(available_slots)
        available_dates = len(graphql_result.available_dates)
        has_slots = total_slots > 0 and available_dates > 0

        # 3. 슬롯 없음 → 예약 불가 (정상 케이스)
        if not has_slots:
            logger.info(f"[NaverDual] GraphQL 성공, 슬롯 없음 (전체:{total_slots}, 가용일:{available_dates})")
            return DualCheckResult(
                can_book=False,
                schedule=graphql_result,
                has_slots=False,
                http_ok=http_ok,
                http_checked=http_checked,
                error_reason="no_slots"
            )

        # 4. 슬롯 있음 + 페이지 확인 실패 → 예약 불가 (확인 불가)
        if not http_checked:
            logger.warning(f"[NaverDual] GraphQL 성공 + 슬롯 {total_slots}개 + 페이지 확인 실패")
            return DualCheckResult(
                can_book=False,
                schedule=graphql_result,
                has_slots=True,
                http_ok=False,
                http_checked=False,
                error_reason="page_check_failed"
            )

        # 5. 슬롯 있음 + 상품 비활성화 → 예약 불가
        if page_result is False:
            logger.warning(f"[NaverDual] GraphQL 성공 + 슬롯 {total_slots}개 + 상품 비활성화")
            return DualCheckResult(
                can_book=False,
                schedule=graphql_result,
                has_slots=True,
                http_ok=False,
                http_checked=True,
                error_reason="inactive"
            )

        # 6. 슬롯 있음 + 상품 활성 → 예약 가능
        logger.info(f"[NaverDual] GraphQL 성공 + 슬롯 {total_slots}개 + 상품 활성 - 예약 가능")
        return DualCheckResult(
            can_book=True,
            schedule=graphql_result,
            has_slots=True,
            http_ok=True,
            http_checked=True,
            error_reason=None
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


def get_naver_graphql_client(
    proxy_manager: Optional["ProxyManager"] = None
) -> NaverGraphQLClient:
    """
    NaverGraphQLClient 싱글톤 인스턴스 반환

    Args:
        proxy_manager: 프록시 매니저 (최초 호출 시에만 적용)

    Returns:
        NaverGraphQLClient 인스턴스
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = NaverGraphQLClient(proxy_manager=proxy_manager)
    return _client_instance


def set_proxy_manager(proxy_manager: Optional["ProxyManager"]):
    """싱글톤 인스턴스에 프록시 매니저 설정 (런타임 변경용)"""
    global _client_instance
    # 인스턴스가 없으면 먼저 생성
    if _client_instance is None:
        _client_instance = NaverGraphQLClient(proxy_manager=proxy_manager)
        logger.info(
            f"[NaverGraphQL] 싱글톤 인스턴스 생성됨 (프록시 매니저: {'있음' if proxy_manager else '없음'})"
        )
    else:
        _client_instance._proxy_manager = proxy_manager
        logger.info(
            f"[NaverGraphQL] 프록시 매니저 {'설정됨' if proxy_manager else '해제됨'}"
        )


async def close_naver_graphql_client():
    """싱글톤 인스턴스 종료"""
    global _client_instance
    if _client_instance:
        await _client_instance.close()
        _client_instance = None
