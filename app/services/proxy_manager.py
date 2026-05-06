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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class _ProxyBucketState:
    """메서드별 프록시 상태."""

    proxy_file: Path
    proxy_list: List[str] = field(default_factory=list)
    active_pool: List[str] = field(default_factory=list)
    current_proxy: Optional[str] = None
    current_index: int = 0
    request_count: int = 0
    blacklist: Dict[str, float] = field(default_factory=dict)
    session_blacklist: Dict[str, str] = field(default_factory=dict)
    slow_count: Dict[str, int] = field(default_factory=dict)
    file_mtime: Optional[float] = None


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
        file_check_interval: int = 300,
    ):
        """
        초기화

        Args:
            proxy_file: 프록시 목록 파일 경로 (기본: shared/proxies/proxy_list.txt)
            rotation_interval: 프록시 교체 주기 (요청 수)
            max_active_pool: 활성 프록시 풀 최대 크기
            connection_timeout: 프록시 연결 타임아웃 (초)
            blacklist_duration: 블랙리스트 유지 시간 (초)
            file_check_interval: 파일 변경 확인 간격 (초)
        """
        self._base_proxy_file = proxy_file or self.DEFAULT_PROXY_FILE
        self.rotation_interval = rotation_interval
        self.max_active_pool = max_active_pool
        self.connection_timeout = connection_timeout
        self.blacklist_duration = blacklist_duration
        self.file_check_interval = file_check_interval

        self._states: Dict[str, _ProxyBucketState] = {
            "get": _ProxyBucketState(proxy_file=self._resolve_proxy_file("get")),
            "post": _ProxyBucketState(proxy_file=self._resolve_proxy_file("post")),
        }

        # 초기화 상태
        self._initialized = False

        logger.info(
            f"ProxyManager 생성 - 파일: {self.proxy_file}, "
            f"로테이션: {rotation_interval}회, 풀: {max_active_pool}개"
        )

    def _normalize_request_method(self, request_method: Optional[str]) -> str:
        """요청 메서드 정규화."""
        method = (request_method or "get").strip().lower()
        return "post" if method == "post" else "get"

    def _resolve_proxy_file(self, request_method: Optional[str]) -> Path:
        """메서드별 프록시 파일 경로 결정."""
        method = self._normalize_request_method(request_method)
        base = self._base_proxy_file

        if base.name != "proxy_list.txt":
            return base

        candidate_name = "proxy_list_post.txt" if method == "post" else "proxy_list_get.txt"
        candidate = base.with_name(candidate_name)
        return candidate if candidate.exists() else base

    def _get_state(self, request_method: Optional[str]) -> _ProxyBucketState:
        """메서드별 상태 반환."""
        method = self._normalize_request_method(request_method)
        state = self._states[method]
        resolved_file = self._resolve_proxy_file(method)
        if state.proxy_file != resolved_file:
            state.proxy_file = resolved_file
        return state

    @property
    def proxy_file(self) -> Path:
        return self._get_state("get").proxy_file

    @property
    def proxy_list(self) -> List[str]:
        return self._get_state("get").proxy_list

    @proxy_list.setter
    def proxy_list(self, value: List[str]) -> None:
        self._get_state("get").proxy_list = value

    @property
    def active_pool(self) -> List[str]:
        return self._get_state("get").active_pool

    @active_pool.setter
    def active_pool(self, value: List[str]) -> None:
        self._get_state("get").active_pool = value

    @property
    def current_proxy(self) -> Optional[str]:
        return self._get_state("get").current_proxy

    @current_proxy.setter
    def current_proxy(self, value: Optional[str]) -> None:
        self._get_state("get").current_proxy = value

    @property
    def current_index(self) -> int:
        return self._get_state("get").current_index

    @current_index.setter
    def current_index(self, value: int) -> None:
        self._get_state("get").current_index = value

    @property
    def request_count(self) -> int:
        return self._get_state("get").request_count

    @request_count.setter
    def request_count(self, value: int) -> None:
        self._get_state("get").request_count = value

    @property
    def blacklist(self) -> Dict[str, float]:
        return self._get_state("get").blacklist

    @blacklist.setter
    def blacklist(self, value: Dict[str, float]) -> None:
        self._get_state("get").blacklist = value

    @property
    def session_blacklist(self) -> Dict[str, str]:
        return self._get_state("get").session_blacklist

    @session_blacklist.setter
    def session_blacklist(self, value: Dict[str, str]) -> None:
        self._get_state("get").session_blacklist = value

    @property
    def slow_count(self) -> Dict[str, int]:
        return self._get_state("get").slow_count

    @slow_count.setter
    def slow_count(self, value: Dict[str, int]) -> None:
        self._get_state("get").slow_count = value

    @property
    def _file_mtime(self) -> Optional[float]:
        return self._get_state("get").file_mtime

    @_file_mtime.setter
    def _file_mtime(self, value: Optional[float]) -> None:
        self._get_state("get").file_mtime = value

    def _cleanup_blacklist(self, request_method: Optional[str] = "get") -> None:
        """만료된 블랙리스트 항목 제거."""
        state = self._get_state(request_method)
        now = time.time()
        expired = [p for p, t in state.blacklist.items() if now >= t]
        for p in expired:
            del state.blacklist[p]
            logger.debug(f"프록시 복구: {p}")

    def load_proxy_list(self, request_method: Optional[str] = "get") -> bool:
        """프록시 리스트 파일에서 로드"""
        state = self._get_state(request_method)
        try:
            proxy_file = self._resolve_proxy_file(request_method)
            state.proxy_file = proxy_file

            if not proxy_file.exists():
                logger.error(f"프록시 파일 없음: {proxy_file}")
                return False

            with open(proxy_file, "r", encoding="utf-8") as f:
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

            state.proxy_list = list(set(proxies))
            state.file_mtime = proxy_file.stat().st_mtime

            logger.info(f"프록시 로드 완료: {len(state.proxy_list)}개 ({request_method or 'get'})")
            return len(state.proxy_list) > 0

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

    async def refresh_active_pool(
        self,
        verbose: bool = True,
        request_method: Optional[str] = "get",
    ) -> bool:
        """
        활성 프록시 풀 재구성 (병렬 검증)

        Args:
            verbose: 상세 로그 출력 여부
        """
        state = self._get_state(request_method)

        if not state.proxy_list:
            logger.error("프록시 리스트가 비어있습니다")
            return False

        self._cleanup_blacklist(request_method)

        # 블랙리스트 제외한 후보
        candidates = [p for p in state.proxy_list if p not in state.blacklist]

        if not candidates:
            logger.warning("모든 프록시가 블랙리스트됨, 초기화")
            state.blacklist.clear()
            candidates = state.proxy_list.copy()

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
                state.blacklist[proxy] = now + self.blacklist_duration
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
                state.blacklist[proxy] = now + self.blacklist_duration
                failed_count += 1

        # 응답 시간순 정렬, 상위 N개 선택
        valid_proxies.sort(key=lambda x: x[1])
        state.active_pool = [proxy for proxy, _ in valid_proxies[: self.max_active_pool]]

        elapsed = time.time() - start_time
        if verbose:
            print(f"\n[ProxyManager] 검증 완료: {len(valid_proxies)}개 유효, {failed_count}개 실패 ({elapsed:.1f}초 소요)")

        if state.active_pool:
            state.current_proxy = state.active_pool[0]
            state.current_index = 0

        logger.info(
            f"활성 프록시 풀 구성 완료: {len(state.active_pool)}개 ({request_method or 'get'})"
        )
        return len(state.active_pool) > 0

    async def initialize(self) -> bool:
        """프록시 매니저 초기화 (로드 + 검증)"""
        logger.info("ProxyManager 초기화 시작")

        if not self.load_proxy_list("get"):
            return False

        # POST 파일이 아직 없으면 GET 호환 파일로 자동 fallback한다.
        self.load_proxy_list("post")

        if not await self.refresh_active_pool(request_method="get"):
            logger.error("유효한 프록시가 없습니다")
            return False

        await self.refresh_active_pool(request_method="post")

        self._initialized = True
        logger.info(f"ProxyManager 초기화 완료 - 활성: {len(self.active_pool)}개")
        return True

    async def check_and_reload(self, request_method: Optional[str] = "get") -> bool:
        """파일 변경 시 리로드 (폴링용)"""
        state = self._get_state(request_method)

        if not state.proxy_file.exists():
            return False

        current_mtime = state.proxy_file.stat().st_mtime

        if state.file_mtime != current_mtime:
            logger.info("프록시 파일 변경 감지, 리로드 시작")
            if self.load_proxy_list(request_method):
                await self.refresh_active_pool(request_method=request_method)
                return True

        return False

    def get_next_proxy(self, request_method: Optional[str] = "get") -> Optional[str]:
        """다음 프록시 반환 (로테이션 적용)"""
        state = self._get_state(request_method)
        state.request_count += 1
        self._cleanup_blacklist(request_method)

        # 활성 풀에서 사용 가능한 프록시 (세션 블랙리스트 + 임시 블랙리스트 제외)
        available = [
            p for p in state.active_pool
            if p not in state.session_blacklist and p not in state.blacklist
        ]

        if not available:
            # 전체 리스트에서 시도 (세션 블랙리스트는 계속 제외)
            available = [
                p for p in state.proxy_list
                if p not in state.session_blacklist and p not in state.blacklist
            ]

        if not available:
            # 임시 블랙리스트만 초기화 (세션 블랙리스트는 유지)
            logger.warning("사용 가능한 프록시 없음, 임시 블랙리스트 초기화")
            state.blacklist.clear()
            available = [
                p for p in (state.active_pool if state.active_pool else state.proxy_list)
                if p not in state.session_blacklist
            ]

        if not available:
            logger.error(f"모든 프록시가 세션 블랙리스트됨 ({len(state.session_blacklist)}개)")
            return None

        # 로테이션 체크
        should_rotate = (
            state.request_count % self.rotation_interval == 1
            or state.current_proxy not in available
        )

        if should_rotate:
            state.current_index = (state.current_index + 1) % len(available)
            old_proxy = state.current_proxy
            state.current_proxy = available[state.current_index]
            if old_proxy != state.current_proxy:
                logger.debug(f"프록시 로테이션: {state.current_proxy}")

        return state.current_proxy

    def get_aiohttp_proxy(self) -> Optional[str]:
        """aiohttp용 프록시 URL 반환"""
        return self.get_next_proxy()

    def get_fresh_proxy(
        self,
        exclude: Optional[set] = None,
        request_method: Optional[str] = "get",
    ) -> Optional[str]:
        """
        새 프록시 반환 (재시도용, 로테이션 무시)

        Args:
            exclude: 제외할 프록시 URL 집합 (이미 시도한 프록시)

        Returns:
            새 프록시 URL 또는 None
        """
        state = self._get_state(request_method)
        self._cleanup_blacklist(request_method)
        exclude = exclude or set()

        # 활성 풀에서 사용 가능한 프록시 (세션 블랙리스트 + 임시 블랙리스트 + exclude 제외)
        available = [
            p for p in state.active_pool
            if p not in state.session_blacklist and p not in state.blacklist and p not in exclude
        ]

        if not available:
            # 전체 리스트에서 시도 (세션 블랙리스트는 계속 제외)
            available = [
                p for p in state.proxy_list
                if p not in state.session_blacklist and p not in state.blacklist and p not in exclude
            ]

        if not available:
            # 모든 프록시를 시도했으면 None 반환
            logger.warning(
                f"사용 가능한 새 프록시 없음 "
                f"(exclude: {len(exclude)}개, session_blacklist: {len(state.session_blacklist)}개, "
                f"blacklist: {len(state.blacklist)}개)"
            )
            return None

        # 순차적으로 다음 프록시 선택 (request_count 기반이 아닌 exclude 크기 기반)
        index = len(exclude) % len(available)
        return available[index]

    def get_playwright_proxy(self) -> Optional[Dict]:
        """Playwright 컨텍스트용 프록시 설정 반환"""
        proxy = self.get_next_proxy("get")
        if not proxy:
            return None

        parsed = urlparse(proxy)

        proxy_config = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}

        # 인증 정보가 있는 경우
        if parsed.username and parsed.password:
            proxy_config["username"] = parsed.username
            proxy_config["password"] = parsed.password

        return proxy_config

    def mark_failed(
        self,
        proxy: str,
        error: str = "unknown",
        request_method: Optional[str] = "get",
    ):
        """프록시 실패 처리 (세션 블랙리스트에 영구 등록)"""
        state = self._get_state(request_method)
        # 부분 매칭 지원 (URL 일부만 전달된 경우)
        matched_proxy = None
        for p in state.proxy_list:
            if proxy in p or p in proxy:
                matched_proxy = p
                break

        if matched_proxy:
            # 세션 블랙리스트에 영구 등록 (에러 메시지 포함)
            state.session_blacklist[matched_proxy] = error
            # 임시 블랙리스트에도 등록 (호환성)
            state.blacklist[matched_proxy] = time.time() + self.blacklist_duration
            logger.warning(f"프록시 세션 블랙리스트 등록: {matched_proxy} - {error}")

            if matched_proxy in state.active_pool:
                state.active_pool.remove(matched_proxy)

            if matched_proxy == state.current_proxy:
                state.current_proxy = None

    def mark_slow(
        self,
        proxy: str,
        response_time: float,
        request_method: Optional[str] = "get",
    ) -> int:
        """
        느린 프록시 처리 - 4단계 점진적 페널티

        Args:
            proxy: 프록시 URL
            response_time: 응답 시간 (초)

        Returns:
            int: 현재 페널티 단계 (1~4)
                1: 풀 맨 뒤로 이동
                2: 현재 풀에서 제거
                3: 다음 풀에서도 제외 (세션 블랙리스트)
                4: DB에 느림 표시 (향후 구현)
        """
        state = self._get_state(request_method)
        # 부분 매칭 지원
        matched_proxy = None
        for p in state.proxy_list:
            if proxy in p or p in proxy:
                matched_proxy = p
                break

        if not matched_proxy:
            return 0

        # 카운트 증가
        state.slow_count[matched_proxy] = state.slow_count.get(matched_proxy, 0) + 1
        count = state.slow_count[matched_proxy]

        if count == 1:
            # 1단계: 풀 맨 뒤로 이동
            if matched_proxy in state.active_pool:
                state.active_pool.remove(matched_proxy)
                state.active_pool.append(matched_proxy)
            logger.info(
                f"프록시 느림 (1/4): {matched_proxy} - {response_time:.2f}s → 풀 맨 뒤로 이동"
            )
            return 1

        elif count == 2:
            # 2단계: 현재 풀에서 제거
            if matched_proxy in state.active_pool:
                state.active_pool.remove(matched_proxy)
            # 임시 블랙리스트에 등록 (풀 갱신 시 복구 가능)
            state.blacklist[matched_proxy] = time.time() + self.blacklist_duration
            logger.warning(
                f"프록시 느림 (2/4): {matched_proxy} - {response_time:.2f}s → 풀에서 제거"
            )

            if matched_proxy == state.current_proxy:
                state.current_proxy = None
            return 2

        elif count == 3:
            # 3단계: 다음 풀에서도 제외 (세션 블랙리스트 등록)
            error_msg = f"slow:{response_time:.1f}s (누적 {count}회)"
            state.session_blacklist[matched_proxy] = error_msg
            state.blacklist[matched_proxy] = time.time() + self.blacklist_duration
            logger.warning(
                f"프록시 느림 (3/4): {matched_proxy} - {response_time:.2f}s → 세션 블랙리스트"
            )

            if matched_proxy in state.active_pool:
                state.active_pool.remove(matched_proxy)
            if matched_proxy == state.current_proxy:
                state.current_proxy = None
            return 3

        else:
            # 4단계 이상: DB 세션 없는 런타임 경로이므로 세션 블랙리스트 유지
            error_msg = f"slow:{response_time:.1f}s (누적 {count}회, DB 기록 대상)"
            state.session_blacklist[matched_proxy] = error_msg
            logger.warning(
                f"프록시 느림 (4/4): {matched_proxy} - {response_time:.2f}s → DB 기록 대상"
            )
            return 4

    def init_slow_count_from_db(
        self,
        timeout_counts: Dict[str, int],
        request_method: Optional[str] = "get",
    ) -> int:
        """
        DB에서 조회한 timeout 카운트로 slow_count 초기화

        워커 시작 시 호출하여 이전 세션의 timeout 이력을 복원

        Args:
            timeout_counts: {proxy_host: timeout_count} 딕셔너리
                           proxy_host는 "host:port" 형식

        Returns:
            초기화된 프록시 수
        """
        state = self._get_state(request_method)
        initialized_count = 0

        for proxy_host, count in timeout_counts.items():
            # proxy_host (host:port) -> proxy_url 매칭
            matched_proxy = None
            for p in state.proxy_list:
                if proxy_host in p:
                    matched_proxy = p
                    break

            if not matched_proxy:
                continue

            # slow_count 설정
            state.slow_count[matched_proxy] = count
            initialized_count += 1

            # 3회 이상이면 세션 블랙리스트에도 등록
            if count >= 3:
                error_msg = f"slow:DB복원 (누적 {count}회)"
                state.session_blacklist[matched_proxy] = error_msg

                # active_pool에서 제거
                if matched_proxy in state.active_pool:
                    state.active_pool.remove(matched_proxy)

                logger.warning(
                    f"프록시 느림 복원: {matched_proxy} - {count}회 → 세션 블랙리스트"
                )

        logger.info(
            f"slow_count DB 초기화 완료: {initialized_count}개 프록시, "
            f"세션 블랙리스트: {len(state.session_blacklist)}개"
        )
        return initialized_count

    def get_status(self, request_method: Optional[str] = "get") -> Dict:
        """현재 프록시 상태 반환"""
        state = self._get_state(request_method)
        return {
            "initialized": self._initialized,
            "request_method": self._normalize_request_method(request_method),
            "total": len(state.proxy_list),
            "active_pool": len(state.active_pool),
            "blacklisted": len(state.blacklist),
            "session_blacklisted": len(state.session_blacklist),
            "session_blacklist_details": dict(state.session_blacklist),  # 프록시 -> 에러 메시지
            "slow_count": len(state.slow_count),  # 느림 기록된 프록시 수
            "slow_details": dict(state.slow_count),  # 프록시 -> 느림 횟수
            "current": state.current_proxy,
            "request_count": state.request_count,
            "next_rotation_in": self.rotation_interval
            - (state.request_count % self.rotation_interval),
            "proxy_file": str(state.proxy_file),
            "by_method": {
                method: {
                    "total": len(bucket.proxy_list),
                    "active_pool": len(bucket.active_pool),
                    "blacklisted": len(bucket.blacklist),
                    "session_blacklisted": len(bucket.session_blacklist),
                    "slow_count": len(bucket.slow_count),
                    "current": bucket.current_proxy,
                    "request_count": bucket.request_count,
                    "proxy_file": str(bucket.proxy_file),
                }
                for method, bucket in self._states.items()
            },
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
