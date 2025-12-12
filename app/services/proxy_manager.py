#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
프록시 매니저 - monitor-page용
- 프록시 품질 검증 (httpbin.org)
- 활성 프록시 풀 관리
- 로테이션 지원
- aiohttp/Playwright 호환 프록시 설정 반환
- 파일 변경 감지 및 자동 리로드
"""

import asyncio
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)


class ProxyManager:
    """프록시 로테이션 매니저"""

    # 공유 프록시 파일 경로 (tools/shared/proxies/)
    DEFAULT_PROXY_FILE = Path(__file__).resolve().parents[3] / "shared" / "proxies" / "proxy_list.txt"

    def __init__(
        self,
        proxy_file: Optional[Path] = None,
        rotation_interval: int = 5,
        max_active_pool: int = 10,
        connection_timeout: int = 5,
        blacklist_duration: int = 300,
    ):
        """
        초기화

        Args:
            proxy_file: 프록시 목록 파일 경로 (기본: shared/proxies/proxy_list.txt)
            rotation_interval: 프록시 교체 주기 (요청 수)
            max_active_pool: 활성 프록시 풀 최대 크기
            connection_timeout: 프록시 연결 타임아웃 (초)
            blacklist_duration: 블랙리스트 유지 시간 (초)
        """
        self.proxy_file = proxy_file or self.DEFAULT_PROXY_FILE
        self.rotation_interval = rotation_interval
        self.max_active_pool = max_active_pool
        self.connection_timeout = connection_timeout
        self.blacklist_duration = blacklist_duration

        # 프록시 관리
        self.proxy_list: List[str] = []
        self.active_pool: List[str] = []
        self.current_proxy: Optional[str] = None
        self.current_index = 0
        self.request_count = 0

        # 블랙리스트 (실패한 프록시 -> 만료 시간) - 임시 블랙리스트
        self.blacklist: Dict[str, float] = {}

        # 세션 블랙리스트 (실패한 프록시 -> 에러 메시지) - 세션 동안 영구
        self.session_blacklist: Dict[str, str] = {}

        # 파일 변경 감지용
        self._file_mtime: Optional[float] = None

        # 초기화 상태
        self._initialized = False

        logger.info(
            f"ProxyManager 생성 - 파일: {self.proxy_file}, "
            f"로테이션: {rotation_interval}회, 풀: {max_active_pool}개"
        )

    def load_proxy_list(self) -> bool:
        """프록시 리스트 파일에서 로드"""
        try:
            if not self.proxy_file.exists():
                logger.error(f"프록시 파일 없음: {self.proxy_file}")
                return False

            with open(self.proxy_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            proxies = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # 주석 제거 (# 이후)
                proxy_url = line.split("#")[0].strip()
                if not proxy_url:
                    continue

                if self._is_valid_proxy(proxy_url):
                    proxies.append(proxy_url)

            self.proxy_list = list(set(proxies))
            self._file_mtime = self.proxy_file.stat().st_mtime

            logger.info(f"프록시 로드 완료: {len(self.proxy_list)}개")
            return len(self.proxy_list) > 0

        except Exception as e:
            logger.error(f"프록시 로드 실패: {e}")
            return False

    def _is_valid_proxy(self, proxy: str) -> bool:
        """프록시 URL 형식 검증"""
        try:
            parsed = urlparse(proxy)
            return (
                parsed.scheme in ["http", "https", "socks5"]
                and parsed.hostname is not None
                and parsed.port is not None
            )
        except Exception:
            return False

    async def validate_proxy(self, proxy: str) -> Tuple[bool, float, Dict]:
        """
        프록시 품질 검증 (httpbin.org/ip 사용)

        Returns:
            (is_valid, response_time, detail_dict)
        """
        start_time = time.time()
        result = {
            "proxy": proxy,
            "valid": False,
            "response_time": 999.0,
            "error": None,
        }

        try:
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=False),
                timeout=aiohttp.ClientTimeout(total=self.connection_timeout),
            ) as session:
                async with session.get("http://httpbin.org/ip", proxy=proxy) as response:
                    if response.status == 200:
                        data = await response.json()
                        response_time = time.time() - start_time
                        result.update(
                            {
                                "valid": True,
                                "response_time": response_time,
                                "ip": data.get("origin", "unknown"),
                            }
                        )

        except asyncio.TimeoutError:
            result["error"] = "timeout"
        except Exception as e:
            result["error"] = str(e)[:50]

        return result["valid"], result["response_time"], result

    async def refresh_active_pool(self, verbose: bool = True) -> bool:
        """
        활성 프록시 풀 재구성 (병렬 검증)

        Args:
            verbose: 상세 로그 출력 여부
        """
        if not self.proxy_list:
            logger.error("프록시 리스트가 비어있습니다")
            return False

        self._cleanup_blacklist()

        # 블랙리스트 제외한 후보
        candidates = [p for p in self.proxy_list if p not in self.blacklist]

        if not candidates:
            logger.warning("모든 프록시가 블랙리스트됨, 초기화")
            self.blacklist.clear()
            candidates = self.proxy_list.copy()

        if verbose:
            print(f"\n[ProxyManager] {len(candidates)}개 프록시 품질 테스트 시작...")
        logger.info(f"{len(candidates)}개 프록시 품질 테스트 시작...")

        start_time = time.time()

        # 병렬 검증
        tasks = [self.validate_proxy(proxy) for proxy in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 유효한 프록시 수집
        valid_proxies = []
        failed_count = 0
        now = time.time()

        for i, result in enumerate(results):
            proxy = candidates[i]

            if isinstance(result, Exception):
                if verbose:
                    print(f"  [FAIL] {proxy} - {str(result)[:40]}")
                logger.debug(f"프록시 검증 예외: {proxy} - {result}")
                self.blacklist[proxy] = now + self.blacklist_duration
                failed_count += 1
                continue

            is_valid, response_time, detail = result

            if is_valid:
                valid_proxies.append((proxy, response_time))
                if verbose:
                    print(f"  [OK]   {proxy} - {response_time:.2f}s")
                logger.debug(f"프록시 유효: {proxy} - {response_time:.2f}s")
            else:
                if verbose:
                    print(f"  [FAIL] {proxy} - {detail.get('error', 'unknown')}")
                logger.debug(f"프록시 무효: {proxy} - {detail.get('error')}")
                self.blacklist[proxy] = now + self.blacklist_duration
                failed_count += 1

        # 응답 시간순 정렬, 상위 N개 선택
        valid_proxies.sort(key=lambda x: x[1])
        self.active_pool = [proxy for proxy, _ in valid_proxies[: self.max_active_pool]]

        elapsed = time.time() - start_time
        if verbose:
            print(f"\n[ProxyManager] 검증 완료: {len(valid_proxies)}개 유효, {failed_count}개 실패 ({elapsed:.1f}초 소요)")

        if self.active_pool:
            self.current_proxy = self.active_pool[0]
            self.current_index = 0

        logger.info(f"활성 프록시 풀 구성 완료: {len(self.active_pool)}개")
        return len(self.active_pool) > 0

    async def initialize(self) -> bool:
        """프록시 매니저 초기화 (로드 + 검증)"""
        logger.info("ProxyManager 초기화 시작")

        if not self.load_proxy_list():
            return False

        if not await self.refresh_active_pool():
            logger.error("유효한 프록시가 없습니다")
            return False

        self._initialized = True
        logger.info(f"ProxyManager 초기화 완료 - 활성: {len(self.active_pool)}개")
        return True

    def _cleanup_blacklist(self):
        """만료된 블랙리스트 항목 제거"""
        now = time.time()
        expired = [p for p, t in self.blacklist.items() if now >= t]
        for p in expired:
            del self.blacklist[p]
            logger.debug(f"프록시 복구: {p}")

    async def check_and_reload(self) -> bool:
        """파일 변경 시 리로드 (폴링용)"""
        if not self.proxy_file.exists():
            return False

        current_mtime = self.proxy_file.stat().st_mtime

        if self._file_mtime != current_mtime:
            logger.info("프록시 파일 변경 감지, 리로드 시작")
            if self.load_proxy_list():
                await self.refresh_active_pool()
                return True

        return False

    def get_next_proxy(self) -> Optional[str]:
        """다음 프록시 반환 (로테이션 적용)"""
        self.request_count += 1
        self._cleanup_blacklist()

        # 활성 풀에서 사용 가능한 프록시 (세션 블랙리스트 + 임시 블랙리스트 제외)
        available = [
            p for p in self.active_pool
            if p not in self.session_blacklist and p not in self.blacklist
        ]

        if not available:
            # 전체 리스트에서 시도 (세션 블랙리스트는 계속 제외)
            available = [
                p for p in self.proxy_list
                if p not in self.session_blacklist and p not in self.blacklist
            ]

        if not available:
            # 임시 블랙리스트만 초기화 (세션 블랙리스트는 유지)
            logger.warning("사용 가능한 프록시 없음, 임시 블랙리스트 초기화")
            self.blacklist.clear()
            available = [
                p for p in (self.active_pool if self.active_pool else self.proxy_list)
                if p not in self.session_blacklist
            ]

        if not available:
            logger.error(f"모든 프록시가 세션 블랙리스트됨 ({len(self.session_blacklist)}개)")
            return None

        # 로테이션 체크
        should_rotate = (
            self.request_count % self.rotation_interval == 1
            or self.current_proxy not in available
        )

        if should_rotate:
            self.current_index = (self.current_index + 1) % len(available)
            old_proxy = self.current_proxy
            self.current_proxy = available[self.current_index]
            if old_proxy != self.current_proxy:
                logger.debug(f"프록시 로테이션: {self.current_proxy}")

        return self.current_proxy

    def get_aiohttp_proxy(self) -> Optional[str]:
        """aiohttp용 프록시 URL 반환"""
        return self.get_next_proxy()

    def get_fresh_proxy(self, exclude: Optional[set] = None) -> Optional[str]:
        """
        새 프록시 반환 (재시도용, 로테이션 무시)

        Args:
            exclude: 제외할 프록시 URL 집합 (이미 시도한 프록시)

        Returns:
            새 프록시 URL 또는 None
        """
        self._cleanup_blacklist()
        exclude = exclude or set()

        # 활성 풀에서 사용 가능한 프록시 (세션 블랙리스트 + 임시 블랙리스트 + exclude 제외)
        available = [
            p for p in self.active_pool
            if p not in self.session_blacklist and p not in self.blacklist and p not in exclude
        ]

        if not available:
            # 전체 리스트에서 시도 (세션 블랙리스트는 계속 제외)
            available = [
                p for p in self.proxy_list
                if p not in self.session_blacklist and p not in self.blacklist and p not in exclude
            ]

        if not available:
            # 모든 프록시를 시도했으면 None 반환
            logger.warning(
                f"사용 가능한 새 프록시 없음 "
                f"(exclude: {len(exclude)}개, session_blacklist: {len(self.session_blacklist)}개, "
                f"blacklist: {len(self.blacklist)}개)"
            )
            return None

        # 순차적으로 다음 프록시 선택 (request_count 기반이 아닌 exclude 크기 기반)
        index = len(exclude) % len(available)
        return available[index]

    def get_playwright_proxy(self) -> Optional[Dict]:
        """Playwright 컨텍스트용 프록시 설정 반환"""
        proxy = self.get_next_proxy()
        if not proxy:
            return None

        parsed = urlparse(proxy)

        proxy_config = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}

        # 인증 정보가 있는 경우
        if parsed.username and parsed.password:
            proxy_config["username"] = parsed.username
            proxy_config["password"] = parsed.password

        return proxy_config

    def mark_failed(self, proxy: str, error: str = "unknown"):
        """프록시 실패 처리 (세션 블랙리스트에 영구 등록)"""
        # 부분 매칭 지원 (URL 일부만 전달된 경우)
        matched_proxy = None
        for p in self.proxy_list:
            if proxy in p or p in proxy:
                matched_proxy = p
                break

        if matched_proxy:
            # 세션 블랙리스트에 영구 등록 (에러 메시지 포함)
            self.session_blacklist[matched_proxy] = error
            # 임시 블랙리스트에도 등록 (호환성)
            self.blacklist[matched_proxy] = time.time() + self.blacklist_duration
            logger.warning(f"프록시 세션 블랙리스트 등록: {matched_proxy} - {error}")

            if matched_proxy in self.active_pool:
                self.active_pool.remove(matched_proxy)

            if matched_proxy == self.current_proxy:
                self.current_proxy = None

    def get_status(self) -> Dict:
        """현재 프록시 상태 반환"""
        return {
            "initialized": self._initialized,
            "total": len(self.proxy_list),
            "active_pool": len(self.active_pool),
            "blacklisted": len(self.blacklist),
            "session_blacklisted": len(self.session_blacklist),
            "session_blacklist_details": dict(self.session_blacklist),  # 프록시 -> 에러 메시지
            "current": self.current_proxy,
            "request_count": self.request_count,
            "next_rotation_in": self.rotation_interval
            - (self.request_count % self.rotation_interval),
            "proxy_file": str(self.proxy_file),
        }

    @property
    def is_available(self) -> bool:
        """프록시 사용 가능 여부 (세션 블랙리스트 제외 후)"""
        if not self._initialized:
            return False
        # 세션 블랙리스트를 제외하고 사용 가능한 프록시가 있는지 확인
        available = [p for p in self.active_pool if p not in self.session_blacklist]
        if not available:
            available = [p for p in self.proxy_list if p not in self.session_blacklist]
        return len(available) > 0


# 싱글톤 인스턴스 (선택적 사용)
_proxy_manager: Optional[ProxyManager] = None


def get_proxy_manager() -> Optional[ProxyManager]:
    """전역 프록시 매니저 인스턴스 반환"""
    return _proxy_manager


async def init_proxy_manager(
    enabled: bool = True, **kwargs
) -> Optional[ProxyManager]:
    """
    전역 프록시 매니저 초기화

    Args:
        enabled: 프록시 사용 여부
        **kwargs: ProxyManager 생성자 인자

    Returns:
        초기화된 ProxyManager 또는 None
    """
    global _proxy_manager

    if not enabled:
        logger.info("프록시 비활성화됨")
        _proxy_manager = None
        return None

    _proxy_manager = ProxyManager(**kwargs)
    if await _proxy_manager.initialize():
        return _proxy_manager
    else:
        _proxy_manager = None
        return None
