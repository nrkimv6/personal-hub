"""
AnonymousMonitor - 익명(비로그인) 모니터링 서비스
작성일: 2025-12-10
요구사항: 익명 모니터링 & 스마트 슬롯 감시 개선

브라우저 탭 없이 GraphQL API를 직접 호출하여 재고를 확인합니다.
재고가 있는 경우에만 로그인 탭을 사용하여 예약을 시도합니다.
"""
import asyncio
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

from app.config import logger, settings
from app.services.naver_graphql_client import (
    NaverGraphQLClient,
    ScheduleInfo,
    ScheduleSlot,
    get_naver_graphql_client,
)


@dataclass
class AvailabilityResult:
    """재고 확인 결과"""
    available: bool  # 예약 가능 여부
    slots: List[ScheduleSlot]  # 예약 가능 슬롯 목록
    all_active_slots: List[ScheduleSlot] = field(default_factory=list)  # 모든 활성 슬롯
    estimated_hours: Optional[Tuple[str, str]] = None  # 추정 영업시간 (시작, 종료)
    error: Optional[str] = None  # 에러 메시지
    # 프록시 정보 (2025-12-11 추가)
    proxy_url: Optional[str] = None  # 사용한 프록시 URL


@dataclass
class SlotStatistics:
    """슬롯 통계 정보"""
    time: str
    bookings: int  # 총 예약 수
    available_days: int  # 예약 가능한 날짜 수
    total_stock: int  # 총 재고


@dataclass
class CacheEntry:
    """캐시 항목"""
    result: AvailabilityResult
    timestamp: float


class AnonymousMonitor:
    """익명(비로그인) 모니터링 서비스"""

    # 동시 요청 제한 설정 (설정에서 가져오거나 기본값 사용)
    MAX_CONCURRENT_REQUESTS = getattr(settings, 'ANONYMOUS_MAX_CONCURRENT', 20)
    REQUEST_INTERVAL_MS = getattr(settings, 'ANONYMOUS_REQUEST_INTERVAL_MS', 100)
    CACHE_TTL_SECONDS = getattr(settings, 'ANONYMOUS_CACHE_TTL_SECONDS', 10)

    def __init__(self, client: Optional[NaverGraphQLClient] = None):
        """
        Args:
            client: NaverGraphQLClient 인스턴스 (없으면 싱글톤 사용)
        """
        self.client = client or get_naver_graphql_client()
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_REQUESTS)
        self._last_request_time: float = 0
        self._slot_history: Dict[str, List[str]] = {}  # 활성 슬롯 이력 (영업시간 학습용)
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def check_availability(
        self,
        business_type_id: int,
        business_id: str,
        biz_item_id: str,
        target_date: str,
        use_cache: bool = True
    ) -> AvailabilityResult:
        """
        익명으로 재고 확인

        Args:
            business_type_id: 업체 타입 ID
            business_id: 업체 ID
            biz_item_id: 상품 ID
            target_date: 대상 날짜 (YYYY-MM-DD)
            use_cache: 캐시 사용 여부

        Returns:
            AvailabilityResult: 재고 확인 결과
        """
        cache_key = f"{business_id}:{biz_item_id}:{target_date}"

        # 캐시 확인
        if use_cache:
            cached = self._get_cached(cache_key)
            if cached:
                logger.debug(f"[AnonymousMonitor] Cache hit for {cache_key}")
                return cached

        # Semaphore로 동시 요청 수 제한
        async with self._semaphore:
            # Rate limiting
            await self._apply_rate_limit()

            try:
                result = await self._do_check(
                    business_type_id, business_id, biz_item_id, target_date
                )

                # 캐시 저장
                if use_cache:
                    self._set_cache(cache_key, result)

                return result

            except asyncio.TimeoutError:
                logger.error(f"[AnonymousMonitor] Timeout for {cache_key}")
                return AvailabilityResult(
                    available=False,
                    slots=[],
                    error="timeout"
                )
            except Exception as e:
                logger.error(f"[AnonymousMonitor] Error for {cache_key}: {e}")
                return AvailabilityResult(
                    available=False,
                    slots=[],
                    error=str(e)
                )

    async def _apply_rate_limit(self):
        """Rate limiting 적용"""
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            interval_sec = self.REQUEST_INTERVAL_MS / 1000

            if elapsed < interval_sec:
                await asyncio.sleep(interval_sec - elapsed)

            self._last_request_time = time.time()

    async def _do_check(
        self,
        business_type_id: int,
        business_id: str,
        biz_item_id: str,
        target_date: str
    ) -> AvailabilityResult:
        """실제 API 호출 및 결과 처리"""
        schedule = await self.client.fetch_schedule(
            business_type_id=business_type_id,
            business_id=business_id,
            biz_item_id=biz_item_id,
            start_date=target_date,
            days_ahead=1  # 단일 날짜만 조회
        )

        # 에러 시에도 사용한 프록시 URL 가져오기
        used_proxy = self.client._last_used_proxy

        if not schedule:
            return AvailabilityResult(
                available=False,
                slots=[],
                estimated_hours=None,
                proxy_url=used_proxy  # 에러 시에도 프록시 정보 전달
            )

        # 해당 날짜의 슬롯만 필터링
        date_slots = schedule.slots_by_date.get(target_date, [])

        # 활성 슬롯 필터링 (재고 설정되었거나 예약 이력 있는 슬롯)
        active_slots = [
            s for s in date_slots
            if s.unit_stock > 0 or s.unit_booking_count > 0 or s.stock > 0
        ]

        # 예약 가능 슬롯 (재고 있고 판매일인 슬롯)
        available_slots = [
            s for s in active_slots
            if s.stock > 0 and s.is_sale_day
        ]

        # 영업시간 추정
        estimated_hours = None
        if active_slots:
            times = sorted([s.time for s in active_slots])
            estimated_hours = (times[0], times[-1])

        # 이력 업데이트 (영업시간 학습용)
        cache_key = f"{business_id}:{biz_item_id}"
        booked_times = [s.time for s in active_slots if s.unit_booking_count > 0]
        if booked_times:
            self._update_slot_history(cache_key, booked_times)

        return AvailabilityResult(
            available=len(available_slots) > 0,
            slots=available_slots,
            all_active_slots=active_slots,
            estimated_hours=estimated_hours,
            proxy_url=schedule.proxy_url
        )

    def _update_slot_history(self, cache_key: str, times: List[str]):
        """슬롯 이력 업데이트 (영업시간 학습)"""
        if cache_key not in self._slot_history:
            self._slot_history[cache_key] = []

        self._slot_history[cache_key].extend(times)

        # 최대 1000개까지만 유지
        if len(self._slot_history[cache_key]) > 1000:
            self._slot_history[cache_key] = self._slot_history[cache_key][-1000:]

    def get_learned_hours(
        self,
        business_id: str,
        biz_item_id: str
    ) -> Optional[Tuple[str, str]]:
        """학습된 영업시간 반환"""
        cache_key = f"{business_id}:{biz_item_id}"
        history = self._slot_history.get(cache_key, [])

        if not history:
            return None

        times = sorted(set(history))
        return (times[0], times[-1])

    def _get_cached(self, cache_key: str) -> Optional[AvailabilityResult]:
        """캐시에서 결과 가져오기"""
        if cache_key not in self._cache:
            return None

        entry = self._cache[cache_key]
        if time.time() - entry.timestamp > self.CACHE_TTL_SECONDS:
            del self._cache[cache_key]
            return None

        return entry.result

    def _set_cache(self, cache_key: str, result: AvailabilityResult):
        """캐시에 결과 저장"""
        self._cache[cache_key] = CacheEntry(
            result=result,
            timestamp=time.time()
        )

        # 오래된 캐시 정리 (100개 초과 시)
        if len(self._cache) > 100:
            self._cleanup_cache()

    def _cleanup_cache(self):
        """만료된 캐시 정리"""
        now = time.time()
        expired_keys = [
            k for k, v in self._cache.items()
            if now - v.timestamp > self.CACHE_TTL_SECONDS
        ]
        for key in expired_keys:
            del self._cache[key]

    async def analyze_slots(
        self,
        business_type_id: int,
        business_id: str,
        biz_item_id: str,
        start_date: str,
        days_ahead: int = 7
    ) -> Dict[str, Any]:
        """
        슬롯 분석 (시간 추천용)

        여러 날짜의 슬롯을 분석하여 활성 시간대와 예약 통계를 반환합니다.

        Args:
            business_type_id: 업체 타입 ID
            business_id: 업체 ID
            biz_item_id: 상품 ID
            start_date: 시작 날짜
            days_ahead: 분석할 기간 (일)

        Returns:
            Dict: {
                "suggested_times": List[SlotStatistics],
                "estimated_hours": {"start": str, "end": str} | None
            }
        """
        schedule = await self.client.fetch_schedule(
            business_type_id=business_type_id,
            business_id=business_id,
            biz_item_id=biz_item_id,
            start_date=start_date,
            days_ahead=days_ahead
        )

        if not schedule:
            return {
                "suggested_times": [],
                "estimated_hours": None
            }

        # 시간별 통계 집계
        slot_stats: Dict[str, Dict[str, int]] = {}

        for slot in schedule.slots:
            if slot.unit_booking_count > 0 or slot.stock > 0 or slot.unit_stock > 0:
                if slot.time not in slot_stats:
                    slot_stats[slot.time] = {
                        "bookings": 0,
                        "available_days": 0,
                        "total_stock": 0
                    }

                slot_stats[slot.time]["bookings"] += slot.unit_booking_count
                slot_stats[slot.time]["total_stock"] += slot.stock

                if slot.stock > 0:
                    slot_stats[slot.time]["available_days"] += 1

        # 정렬 (예약 많은 순)
        suggested = sorted(
            slot_stats.items(),
            key=lambda x: (-x[1]["bookings"], x[0])
        )

        suggested_times = [
            SlotStatistics(
                time=t,
                bookings=s["bookings"],
                available_days=s["available_days"],
                total_stock=s["total_stock"]
            )
            for t, s in suggested
        ]

        # 영업시간 추정
        estimated_hours = None
        if suggested:
            times = sorted([t[0] for t in suggested])
            estimated_hours = {
                "start": times[0],
                "end": times[-1]
            }

        return {
            "suggested_times": suggested_times,
            "estimated_hours": estimated_hours
        }


# 싱글톤 인스턴스
_anonymous_monitor_instance: Optional[AnonymousMonitor] = None


def get_anonymous_monitor() -> AnonymousMonitor:
    """AnonymousMonitor 싱글톤 인스턴스 반환"""
    global _anonymous_monitor_instance
    if _anonymous_monitor_instance is None:
        _anonymous_monitor_instance = AnonymousMonitor()
    return _anonymous_monitor_instance
