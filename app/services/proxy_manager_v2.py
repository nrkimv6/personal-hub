"""
DB 기반 프록시 매니저 V2
작성일: 2025-12-11
수정일: 2025-12-12

Features:
- 우선순위 점수 기반 프록시 선택 (가중치 랜덤)
- 적응형 타임아웃 (프록시별 평균 응답시간 기반)
- 메모리 기반 통계 누적 (모니터링 중 DB 쓰기 없음)
- 풀 갱신 시 배치 DB 쓰기 (별도 스레드)
- 직전 풀/느린 프록시 제외
"""
import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Set, TYPE_CHECKING

from app.schemas.proxy import ProxyInfo, ProxyUsageStats

if TYPE_CHECKING:
    from app.services.proxy_db_service import ProxyDBService
    from app.utils.async_db_writer import AsyncDBWriter

logger = logging.getLogger(__name__)


class ProxyManagerV2:
    """
    DB 기반 프록시 매니저

    기존 ProxyManager와 달리 DB에서 프록시를 조회하고,
    사용 결과를 DB에 기록하여 영구적인 품질 관리가 가능합니다.
    """

    def __init__(
        self,
        db_service: "ProxyDBService",
        pool_size: int = 10,
        min_success_rate: float = 0.5,
        pool_refresh_interval: int = 300,
        adaptive_timeout_enabled: bool = True,
        adaptive_timeout_multiplier: float = 2.0,
        adaptive_timeout_min: float = 3.0,
        adaptive_timeout_max: float = 10.0,
        weighted_selection: bool = True,
        max_response_time: float = 2.0,
        db_writer: Optional["AsyncDBWriter"] = None,
        # 쿨다운 설정 (2025-12-12)
        proxy_cooldown_seconds: float = 10.0,
        # 응답시간 기반 풀 구성 (2025-12-12)
        fast_response_threshold: float = 0.5,
        fast_proxy_ratio: float = 0.7,
        normal_response_threshold: float = 2.0,
    ):
        """
        Args:
            db_service: ProxyDBService 인스턴스
            pool_size: 활성 풀 크기 (기본: 10)
            min_success_rate: 최소 성공률 (0.0~1.0, 기본: 0.5)
            pool_refresh_interval: 풀 갱신 주기 (초, 기본: 300)
            adaptive_timeout_enabled: 적응형 타임아웃 사용 여부
            adaptive_timeout_multiplier: 평균 응답시간 배수
            adaptive_timeout_min: 최소 타임아웃 (초)
            adaptive_timeout_max: 최대 타임아웃 (초)
            weighted_selection: 가중치 기반 선택 사용 여부
            max_response_time: 최대 허용 응답시간 (초) - 초과 시 다음 풀에서 제외
            db_writer: 비동기 DB Writer (배치 쓰기용)
            proxy_cooldown_seconds: 프록시 재사용 금지 시간 (초, 기본: 10)
            fast_response_threshold: fast 프록시 기준 응답시간 (초, 기본: 0.5)
            fast_proxy_ratio: fast 프록시 비율 (0.0~1.0, 기본: 0.7 = 70%)
            normal_response_threshold: normal 프록시 최대 응답시간 (초, 기본: 2.0)
        """
        self._db_service = db_service
        self._pool_size = pool_size
        self._min_success_rate = min_success_rate
        self._pool_refresh_interval = pool_refresh_interval
        self._adaptive_timeout_enabled = adaptive_timeout_enabled
        self._adaptive_timeout_multiplier = adaptive_timeout_multiplier
        self._adaptive_timeout_min = adaptive_timeout_min
        self._adaptive_timeout_max = adaptive_timeout_max
        self._weighted_selection = weighted_selection
        self._max_response_time = max_response_time
        self._db_writer = db_writer

        # 쿨다운 설정 (2025-12-12)
        self._proxy_cooldown_seconds = proxy_cooldown_seconds
        self._proxy_last_used: Dict[int, float] = {}  # proxy_id → last_used_timestamp

        # 응답시간 기반 풀 구성 설정 (2025-12-12)
        self._fast_response_threshold = fast_response_threshold
        self._fast_proxy_ratio = fast_proxy_ratio
        self._normal_response_threshold = normal_response_threshold

        # 활성 풀
        self._active_pool: List[ProxyInfo] = []
        self._last_refresh: Optional[datetime] = None
        self._lock = asyncio.Lock()

        # 로테이션 (weighted_selection=False일 때 사용)
        self._current_index = 0

        # 상태
        self._initialized = False
        self._enabled = True

        # 메모리 통계 (풀 갱신 시까지 누적, DB 쓰기 없음)
        self._usage_stats: Dict[int, ProxyUsageStats] = {}

        # 풀 관리 (다음 풀에서 제외할 프록시)
        self._previous_pool_ids: Set[int] = set()  # 직전 풀 프록시 ID
        self._slow_proxies: Set[int] = set()  # 느린 프록시 ID (응답시간 > max_response_time)

    @property
    def is_available(self) -> bool:
        """프록시 사용 가능 여부"""
        return self._enabled and self._initialized and len(self._active_pool) > 0

    @property
    def pool_size(self) -> int:
        """현재 활성 풀 크기"""
        return len(self._active_pool)

    @property
    def is_initialized(self) -> bool:
        """초기화 여부"""
        return self._initialized

    async def initialize(self) -> bool:
        """
        초기화: DB에서 상위 프록시 로드

        Returns:
            초기화 성공 여부
        """
        try:
            await self._refresh_pool()
            self._initialized = True
            logger.info(
                f"ProxyManagerV2 initialized with {len(self._active_pool)} proxies"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to initialize ProxyManagerV2: {e}")
            return False

    async def _refresh_pool(self) -> None:
        """
        활성 풀 갱신 (응답시간 기반 70/30 비율 적용)

        1. 종료된 풀 정보 보존
        2. 새 풀 구성 (DB 읽기) - 70% fast + 30% normal
        3. 새 풀로 즉시 전환
        4. 종료된 풀 통계 → 별도 스레드에서 DB 쓰기
        """
        async with self._lock:
            try:
                # 1. 종료된 풀 정보 보존
                old_pool_ids = {p.id for p in self._active_pool}
                old_stats = dict(self._usage_stats)

                # 2. 새 풀 구성 - 70% fast + 30% normal
                exclude_ids = list(self._previous_pool_ids | self._slow_proxies)

                # 목표 개수 계산
                fast_count = int(self._pool_size * self._fast_proxy_ratio)  # 70%
                normal_count = self._pool_size - fast_count  # 30%

                # 2-1. Fast 프록시 조회 (응답시간 <= 0.5초)
                fast_proxies = self._db_service.get_proxies_by_response_time(
                    max_response_time=self._fast_response_threshold,
                    limit=fast_count,
                    status="active",
                    exclude_ids=exclude_ids if exclude_ids else None,
                    min_success_rate=self._min_success_rate,
                )

                # 2-2. Normal 프록시 조회 (0.5초 < 응답시간 <= 2.0초)
                used_ids = exclude_ids + [p.id for p in fast_proxies]
                normal_proxies = self._db_service.get_proxies_by_response_time(
                    min_response_time=self._fast_response_threshold,
                    max_response_time=self._normal_response_threshold,
                    limit=normal_count,
                    status="active",
                    exclude_ids=used_ids if used_ids else None,
                    min_success_rate=self._min_success_rate,
                )

                # 2-3. 부족분 처리
                proxies = fast_proxies + normal_proxies
                shortage = self._pool_size - len(proxies)

                if shortage > 0:
                    # fast가 부족하면 normal 범위에서 추가
                    if len(fast_proxies) < fast_count:
                        extra_normal = self._db_service.get_proxies_by_response_time(
                            min_response_time=self._fast_response_threshold,
                            max_response_time=self._normal_response_threshold,
                            limit=shortage,
                            status="active",
                            exclude_ids=[p.id for p in proxies] + exclude_ids,
                            min_success_rate=self._min_success_rate,
                        )
                        proxies.extend(extra_normal)
                        shortage = self._pool_size - len(proxies)

                    # 여전히 부족하면 pending 상태 프록시 추가
                    if shortage > 0:
                        pending_proxies = self._db_service.get_top_proxies_for_pool(
                            limit=shortage,
                            status="pending",
                            exclude_ids=[p.id for p in proxies] + exclude_ids,
                        )
                        proxies.extend(pending_proxies)

                # 3. 새 풀로 즉시 전환
                self._previous_pool_ids = old_pool_ids
                self._active_pool = proxies
                self._usage_stats.clear()
                self._slow_proxies.clear()
                self._last_refresh = datetime.now()
                self._current_index = 0

                logger.info(
                    f"Pool refreshed: {len(proxies)} proxies "
                    f"(fast: {len(fast_proxies)}, normal: {len(normal_proxies)}, "
                    f"excluded: {len(exclude_ids)})"
                )

                # 4. 종료된 풀 통계 → 별도 스레드에서 DB 쓰기
                if old_stats:
                    self._schedule_batch_db_write(old_stats)

            except Exception as e:
                logger.error(f"Failed to refresh proxy pool: {e}")

    async def _maybe_refresh_pool(self) -> None:
        """필요시 풀 갱신 (주기적 갱신)"""
        if self._last_refresh is None:
            await self._refresh_pool()
            return

        elapsed = (datetime.now() - self._last_refresh).total_seconds()
        if elapsed >= self._pool_refresh_interval:
            await self._refresh_pool()

    def _sync_refresh_pool(self) -> None:
        """동기적으로 풀 갱신 (풀 고갈 시 호출, 70/30 비율 적용)"""
        try:
            # 긴급 갱신이므로 직전 풀 제외 없이 조회 (느린 프록시만 제외)
            exclude_ids = list(self._slow_proxies) if self._slow_proxies else []

            # 목표 개수 계산
            fast_count = int(self._pool_size * self._fast_proxy_ratio)  # 70%
            normal_count = self._pool_size - fast_count  # 30%

            # Fast 프록시 조회 (응답시간 <= 0.5초)
            fast_proxies = self._db_service.get_proxies_by_response_time(
                max_response_time=self._fast_response_threshold,
                limit=fast_count,
                status="active",
                exclude_ids=exclude_ids if exclude_ids else None,
                min_success_rate=self._min_success_rate,
            )

            # Normal 프록시 조회 (0.5초 < 응답시간 <= 2.0초)
            used_ids = exclude_ids + [p.id for p in fast_proxies]
            normal_proxies = self._db_service.get_proxies_by_response_time(
                min_response_time=self._fast_response_threshold,
                max_response_time=self._normal_response_threshold,
                limit=normal_count,
                status="active",
                exclude_ids=used_ids if used_ids else None,
                min_success_rate=self._min_success_rate,
            )

            # 부족분 처리
            proxies = fast_proxies + normal_proxies
            shortage = self._pool_size - len(proxies)

            if shortage > 0:
                # pending 상태 프록시 추가
                pending_proxies = self._db_service.get_top_proxies_for_pool(
                    limit=shortage,
                    status="pending",
                    exclude_ids=[p.id for p in proxies] + exclude_ids,
                )
                proxies.extend(pending_proxies)

            self._active_pool = proxies
            self._last_refresh = datetime.now()
            self._current_index = 0

            logger.info(
                f"Pool sync-refreshed: {len(proxies)} proxies "
                f"(fast: {len(fast_proxies)}, normal: {len(normal_proxies)})"
            )
        except Exception as e:
            logger.error(f"Failed to sync-refresh proxy pool: {e}")

    def _schedule_batch_db_write(self, stats: Dict[int, ProxyUsageStats]) -> None:
        """배치 DB 쓰기 예약 (별도 스레드)"""
        if not stats:
            return

        # 통계를 dict 리스트로 변환
        stats_list = [
            {
                "proxy_id": s.proxy_id,
                "success_count": s.success_count,
                "fail_count": s.fail_count,
                "avg_response_time": s.avg_response_time,
                "min_response_time": s.min_response_time,
                "max_response_time": s.max_response_time,
            }
            for s in stats.values()
            if s.request_count > 0
        ]

        if not stats_list:
            return

        if self._db_writer:
            # 비동기 DB Writer 사용 (논블로킹)
            self._db_writer.write_nowait(
                self._db_service.batch_update_proxy_stats,
                stats_list,
            )
            logger.debug(f"Scheduled batch DB write for {len(stats_list)} proxies")
        else:
            # fallback: 동기 처리 (블로킹)
            try:
                self._db_service.batch_update_proxy_stats(stats_list)
                logger.debug(f"Batch DB write completed for {len(stats_list)} proxies")
            except Exception as e:
                logger.error(f"Failed to batch update proxy stats: {e}")

    def _get_or_create_stats(self, proxy_id: int) -> ProxyUsageStats:
        """프록시 통계 가져오기 또는 생성"""
        if proxy_id not in self._usage_stats:
            self._usage_stats[proxy_id] = ProxyUsageStats(proxy_id=proxy_id)
        return self._usage_stats[proxy_id]

    def get_next_proxy(self) -> Optional[ProxyInfo]:
        """
        다음 프록시 선택 (쿨다운 적용)

        weighted_selection=True: 우선순위 점수 기반 가중치 랜덤
        weighted_selection=False: 라운드 로빈

        선택된 프록시는 풀의 맨 뒤로 이동하여 재사용 간격을 최대화합니다.
        쿨다운 중인 프록시는 선택에서 제외됩니다.

        Returns:
            선택된 ProxyInfo 또는 None
        """
        # 풀이 비었거나 너무 적으면 동기적으로 갱신 시도
        if len(self._active_pool) < 3:
            self._sync_refresh_pool()

        if not self._active_pool:
            return None

        # 쿨다운 지난 프록시만 필터링
        available = [p for p in self._active_pool if self._is_cooldown_passed(p.id)]

        if not available:
            # 모든 프록시가 쿨다운 중 - 가장 오래된 것 선택 (fallback)
            logger.warning(
                f"All {len(self._active_pool)} proxies in cooldown, "
                f"selecting oldest used proxy"
            )
            # 마지막 사용 시간이 가장 오래된 프록시 선택
            oldest_proxy = min(
                self._active_pool,
                key=lambda p: self._proxy_last_used.get(p.id, 0)
            )
            self._mark_proxy_used(oldest_proxy.id)
            self._move_to_back(oldest_proxy)
            return oldest_proxy

        if self._weighted_selection:
            weights = [max(p.priority_score, 1.0) for p in available]
            proxy = random.choices(available, weights=weights, k=1)[0]
        else:
            proxy = available[0]

        # 프록시 사용 시간 기록
        self._mark_proxy_used(proxy.id)

        # 선택된 프록시를 풀의 맨 뒤로 이동 (재사용 간격 최대화)
        self._move_to_back(proxy)

        # 주기적으로 오래된 쿨다운 기록 정리
        if len(self._proxy_last_used) > self._pool_size * 5:
            self._cleanup_cooldown_records()

        return proxy

    def _move_to_back(self, proxy: ProxyInfo) -> None:
        """선택된 프록시를 풀의 맨 뒤로 이동"""
        try:
            idx = None
            for i, p in enumerate(self._active_pool):
                if p.id == proxy.id:
                    idx = i
                    break
            if idx is not None:
                self._active_pool.append(self._active_pool.pop(idx))
        except (ValueError, IndexError):
            pass  # 이미 제거된 경우 무시

    def _weighted_random_select(self) -> ProxyInfo:
        """우선순위 점수 기반 가중치 랜덤 선택"""
        # 점수가 0인 프록시도 선택 가능하도록 최소값 보장
        weights = [max(p.priority_score, 1.0) for p in self._active_pool]
        return random.choices(self._active_pool, weights=weights, k=1)[0]

    def _round_robin_select(self) -> ProxyInfo:
        """라운드 로빈 선택"""
        proxy = self._active_pool[self._current_index]
        self._current_index = (self._current_index + 1) % len(self._active_pool)
        return proxy

    def _is_cooldown_passed(self, proxy_id: int) -> bool:
        """
        프록시 쿨다운 경과 여부 확인

        Args:
            proxy_id: 프록시 ID

        Returns:
            True: 쿨다운 경과됨 (재사용 가능)
            False: 쿨다운 중 (재사용 불가)
        """
        last_used = self._proxy_last_used.get(proxy_id)
        if last_used is None:
            return True
        return (time.time() - last_used) >= self._proxy_cooldown_seconds

    def _mark_proxy_used(self, proxy_id: int) -> None:
        """
        프록시 사용 시간 기록

        Args:
            proxy_id: 프록시 ID
        """
        self._proxy_last_used[proxy_id] = time.time()

    def _cleanup_cooldown_records(self) -> None:
        """오래된 쿨다운 기록 정리 (메모리 누수 방지)"""
        current_time = time.time()
        expired_ids = [
            proxy_id for proxy_id, last_used in self._proxy_last_used.items()
            if (current_time - last_used) > self._proxy_cooldown_seconds * 10
        ]
        for proxy_id in expired_ids:
            del self._proxy_last_used[proxy_id]

    def get_timeout_for_proxy(self, proxy: ProxyInfo) -> float:
        """
        프록시별 적응형 타임아웃 계산

        Args:
            proxy: 대상 프록시

        Returns:
            타임아웃 (초)
        """
        if not self._adaptive_timeout_enabled:
            return self._adaptive_timeout_max / 2  # 기본값 반환

        if proxy.avg_response_time is None:
            return self._adaptive_timeout_max / 2  # 기본값 (5초)

        # 평균 응답시간 * 배수
        timeout = proxy.avg_response_time * self._adaptive_timeout_multiplier

        # 범위 제한
        return max(
            self._adaptive_timeout_min,
            min(self._adaptive_timeout_max, timeout)
        )

    def get_aiohttp_proxy(self, proxy: Optional[ProxyInfo] = None) -> Optional[str]:
        """
        aiohttp용 프록시 URL 반환

        Args:
            proxy: 특정 프록시 (None이면 자동 선택)

        Returns:
            프록시 URL 또는 None
        """
        if proxy is None:
            proxy = self.get_next_proxy()

        if proxy is None:
            return None

        return proxy.to_aiohttp_proxy()

    def get_playwright_proxy(self, proxy: Optional[ProxyInfo] = None) -> Optional[dict]:
        """
        Playwright용 프록시 설정 반환

        Args:
            proxy: 특정 프록시 (None이면 자동 선택)

        Returns:
            Playwright 프록시 설정 dict 또는 None
        """
        if proxy is None:
            proxy = self.get_next_proxy()

        if proxy is None:
            return None

        return proxy.to_playwright_proxy()

    def report_success(
        self,
        proxy: ProxyInfo,
        response_time: float,
        detected_ip: Optional[str] = None,
        is_anonymous: Optional[bool] = None,
    ) -> None:
        """
        성공 보고: 메모리에만 기록 (DB 쓰기 없음, 논블로킹)

        풀 갱신 시점에 배치로 DB에 저장됩니다.

        Args:
            proxy: 사용된 프록시
            response_time: 응답 시간 (초)
            detected_ip: 감지된 IP (현재 미사용, 향후 확장용)
            is_anonymous: 익명성 여부 (현재 미사용, 향후 확장용)
        """
        # 메모리 통계 업데이트
        stats = self._get_or_create_stats(proxy.id)
        stats.record_success(response_time)

        # 느린 프록시 마킹 및 즉시 풀에서 제거
        if response_time > self._max_response_time:
            self._slow_proxies.add(proxy.id)
            # 현재 풀에서도 즉시 제거 (재사용 방지)
            self._active_pool = [p for p in self._active_pool if p.id != proxy.id]
            logger.warning(
                f"Proxy {proxy.id} removed from pool - too slow "
                f"({response_time:.2f}s > {self._max_response_time}s), "
                f"pool size: {len(self._active_pool)}"
            )

        # 로컬 캐시 업데이트 (풀 내 프록시 정보)
        self._update_local_proxy(proxy.id, is_valid=True, response_time=response_time)

        logger.debug(f"Proxy {proxy.id} success recorded: {response_time:.2f}s (memory only)")

    def report_failure(
        self,
        proxy: ProxyInfo,
        error_type: str,
        error_message: Optional[str] = None,
        http_status: Optional[int] = None,
    ) -> None:
        """
        실패 보고: 메모리에만 기록 (DB 쓰기 없음, 논블로킹)

        풀 갱신 시점에 배치로 DB에 저장됩니다.

        Args:
            proxy: 사용된 프록시
            error_type: 에러 유형 (timeout, connection, http_4xx 등)
            error_message: 에러 메시지
            http_status: HTTP 상태 코드 (현재 미사용, 향후 확장용)
        """
        # 메모리 통계 업데이트
        stats = self._get_or_create_stats(proxy.id)
        stats.record_failure(error_type, error_message)

        # 로컬 캐시 업데이트 및 필요시 풀에서 제거
        self._update_local_proxy(proxy.id, is_valid=False)

        logger.debug(f"Proxy {proxy.id} failure recorded: {error_type} (memory only)")

    def _update_local_proxy(
        self,
        proxy_id: int,
        is_valid: bool,
        response_time: Optional[float] = None,
    ) -> None:
        """
        로컬 풀의 프록시 정보 업데이트

        연속 실패 시 풀에서 제거
        """
        for i, proxy in enumerate(self._active_pool):
            if proxy.id == proxy_id:
                if is_valid:
                    proxy.success_count += 1
                    proxy.fail_count = 0
                    proxy.total_checks += 1
                    if response_time:
                        # 간단한 이동 평균
                        if proxy.avg_response_time:
                            proxy.avg_response_time = (
                                proxy.avg_response_time * 0.8 + response_time * 0.2
                            )
                        else:
                            proxy.avg_response_time = response_time
                else:
                    proxy.fail_count += 1
                    proxy.total_checks += 1

                    # 연속 3회 실패 시 풀에서 제거
                    if proxy.fail_count >= 3:
                        self._active_pool.pop(i)
                        logger.info(
                            f"Proxy {proxy_id} removed from pool (consecutive failures)"
                        )
                break

    def get_fresh_proxy(self, exclude: Optional[Set[str]] = None) -> Optional[str]:
        """
        새 프록시 URL 반환 (재시도용, 기존 ProxyManager 호환, 쿨다운 적용)

        exclude에 포함된 프록시 URL을 제외하고 다음 프록시를 반환합니다.
        쿨다운 중인 프록시도 제외됩니다.

        Args:
            exclude: 제외할 프록시 URL 집합 (이미 시도한 프록시)

        Returns:
            새 프록시 URL 또는 None
        """
        exclude = exclude or set()

        # 풀이 비었거나 너무 적으면 동기적으로 갱신 시도
        if len(self._active_pool) < 3:
            self._sync_refresh_pool()

        if not self._active_pool:
            return None

        # exclude에 포함되지 않고 쿨다운 지난 프록시 필터링
        available = [
            p for p in self._active_pool
            if p.to_aiohttp_proxy() not in exclude and self._is_cooldown_passed(p.id)
        ]

        if not available:
            # 쿨다운 무시하고 exclude만 적용
            available = [
                p for p in self._active_pool
                if p.to_aiohttp_proxy() not in exclude
            ]
            if available:
                logger.warning(
                    f"All non-excluded proxies in cooldown, ignoring cooldown"
                )

        if not available:
            # 모든 프록시가 exclude에 포함된 경우
            logger.warning(
                f"No fresh proxy available (exclude: {len(exclude)}, pool: {len(self._active_pool)})"
            )
            return None

        # 가중치 선택 또는 라운드로빈
        if self._weighted_selection:
            weights = [max(p.priority_score, 1.0) for p in available]
            proxy = random.choices(available, weights=weights, k=1)[0]
        else:
            proxy = available[0]

        # 프록시 사용 시간 기록
        self._mark_proxy_used(proxy.id)

        # 선택된 프록시를 풀의 맨 뒤로 이동
        self._move_to_back(proxy)

        return proxy.to_aiohttp_proxy()

    def mark_failed(self, proxy_url: str, reason: str) -> None:
        """
        기존 ProxyManager 호환 인터페이스

        Args:
            proxy_url: 프록시 URL
            reason: 실패 사유
        """
        for proxy in self._active_pool:
            if proxy.url == proxy_url or proxy.to_aiohttp_proxy() == proxy_url:
                # 동기 호출이므로 DB 기록은 생략, 로컬만 업데이트
                proxy.fail_count += 1
                if proxy.fail_count >= 3:
                    self._active_pool.remove(proxy)
                    logger.info(f"Proxy {proxy.id} removed from pool: {reason}")
                break

    def enable(self) -> None:
        """프록시 활성화"""
        self._enabled = True
        logger.info("ProxyManagerV2 enabled")

    def disable(self) -> None:
        """프록시 비활성화"""
        self._enabled = False
        logger.info("ProxyManagerV2 disabled")

    def get_status(self) -> dict:
        """
        현재 상태 반환 (기존 ProxyManager 호환)

        Returns:
            상태 정보 dict
        """
        return {
            "enabled": self._enabled,
            "initialized": self._initialized,
            "pool_size": len(self._active_pool),
            "target_pool_size": self._pool_size,
            "min_success_rate": self._min_success_rate,
            "max_response_time": self._max_response_time,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "adaptive_timeout_enabled": self._adaptive_timeout_enabled,
            "weighted_selection": self._weighted_selection,
            "pending_stats_count": len(self._usage_stats),
            "slow_proxies_count": len(self._slow_proxies),
            "previous_pool_size": len(self._previous_pool_ids),
            "proxies": [
                {
                    "id": p.id,
                    "url": f"{p.protocol}://{p.host}:{p.port}",
                    "priority_score": p.priority_score,
                    "avg_response_time": p.avg_response_time,
                    "success_rate": p.success_rate,
                    "fail_count": p.fail_count,
                }
                for p in self._active_pool
            ],
        }

    async def shutdown(self) -> None:
        """
        매니저 종료 - 남은 통계를 DB에 저장

        애플리케이션 종료 시 호출하여 미저장 통계 손실 방지
        """
        if self._usage_stats:
            logger.info(f"Flushing {len(self._usage_stats)} pending stats before shutdown")
            self._schedule_batch_db_write(self._usage_stats)
            self._usage_stats.clear()
