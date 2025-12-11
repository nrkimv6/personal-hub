"""
DB 기반 프록시 매니저 V2
작성일: 2025-12-11

Features:
- 우선순위 점수 기반 프록시 선택 (가중치 랜덤)
- 적응형 타임아웃 (프록시별 평균 응답시간 기반)
- 실시간 품질 피드백 (성공/실패 시 DB 기록)
- DB 기반 상태 관리 (영구 저장)
"""
import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import List, Optional, TYPE_CHECKING

from app.schemas.proxy import ProxyInfo

if TYPE_CHECKING:
    from app.services.proxy_db_service import ProxyDBService

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

        # 활성 풀
        self._active_pool: List[ProxyInfo] = []
        self._last_refresh: Optional[datetime] = None
        self._lock = asyncio.Lock()

        # 로테이션 (weighted_selection=False일 때 사용)
        self._current_index = 0

        # 상태
        self._initialized = False
        self._enabled = True

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
        """활성 풀 갱신: DB에서 우선순위 상위 N개 조회"""
        async with self._lock:
            try:
                proxies = self._db_service.get_top_proxies_for_pool(
                    limit=self._pool_size,
                    status="active",
                    min_success_rate=self._min_success_rate,
                )

                # pending 상태의 프록시도 포함 (신규 프록시 테스트용)
                if len(proxies) < self._pool_size:
                    pending_proxies = self._db_service.get_top_proxies_for_pool(
                        limit=self._pool_size - len(proxies),
                        status="pending",
                    )
                    proxies.extend(pending_proxies)

                self._active_pool = proxies
                self._last_refresh = datetime.now()
                self._current_index = 0

                logger.debug(f"Pool refreshed with {len(proxies)} proxies")
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
        """동기적으로 풀 갱신 (풀 고갈 시 호출)"""
        try:
            proxies = self._db_service.get_top_proxies_for_pool(
                limit=self._pool_size,
                status="active",
                min_success_rate=self._min_success_rate,
            )

            # pending 상태의 프록시도 포함 (신규 프록시 테스트용)
            if len(proxies) < self._pool_size:
                pending_proxies = self._db_service.get_top_proxies_for_pool(
                    limit=self._pool_size - len(proxies),
                    status="pending",
                )
                proxies.extend(pending_proxies)

            self._active_pool = proxies
            self._last_refresh = datetime.now()
            self._current_index = 0

            logger.info(f"Pool sync-refreshed with {len(proxies)} proxies (was depleted)")
        except Exception as e:
            logger.error(f"Failed to sync-refresh proxy pool: {e}")

    def get_next_proxy(self) -> Optional[ProxyInfo]:
        """
        다음 프록시 선택

        weighted_selection=True: 우선순위 점수 기반 가중치 랜덤
        weighted_selection=False: 라운드 로빈

        Returns:
            선택된 ProxyInfo 또는 None
        """
        # 풀이 비었거나 너무 적으면 동기적으로 갱신 시도
        if len(self._active_pool) < 3:
            self._sync_refresh_pool()

        if not self._active_pool:
            return None

        if self._weighted_selection:
            return self._weighted_random_select()
        else:
            return self._round_robin_select()

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

    async def report_success(
        self,
        proxy: ProxyInfo,
        response_time: float,
        detected_ip: Optional[str] = None,
        is_anonymous: Optional[bool] = None,
    ) -> None:
        """
        성공 보고: DB에 이력 저장

        Args:
            proxy: 사용된 프록시
            response_time: 응답 시간 (초)
            detected_ip: 감지된 IP
            is_anonymous: 익명성 여부
        """
        try:
            self._db_service.record_check_result(
                proxy_id=proxy.id,
                is_valid=True,
                response_time=response_time,
                detected_ip=detected_ip,
                is_anonymous=is_anonymous,
            )

            # 로컬 캐시 업데이트
            self._update_local_proxy(proxy.id, is_valid=True, response_time=response_time)

            logger.debug(f"Proxy {proxy.id} success reported: {response_time:.2f}s")
        except Exception as e:
            logger.error(f"Failed to report success for proxy {proxy.id}: {e}")

    async def report_failure(
        self,
        proxy: ProxyInfo,
        error_type: str,
        error_message: str,
        http_status: Optional[int] = None,
    ) -> None:
        """
        실패 보고: DB에 이력 저장 및 풀에서 제거 고려

        Args:
            proxy: 사용된 프록시
            error_type: 에러 유형 (timeout, connection, http_4xx 등)
            error_message: 에러 메시지
            http_status: HTTP 상태 코드
        """
        try:
            self._db_service.record_check_result(
                proxy_id=proxy.id,
                is_valid=False,
                error_type=error_type,
                error_message=error_message,
                http_status=http_status,
            )

            # 로컬 캐시 업데이트 및 필요시 풀에서 제거
            self._update_local_proxy(proxy.id, is_valid=False)

            logger.debug(f"Proxy {proxy.id} failure reported: {error_type}")
        except Exception as e:
            logger.error(f"Failed to report failure for proxy {proxy.id}: {e}")

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
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "adaptive_timeout_enabled": self._adaptive_timeout_enabled,
            "weighted_selection": self._weighted_selection,
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
