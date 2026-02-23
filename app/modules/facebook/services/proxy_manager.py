"""Facebook Proxy Manager - IP 차단 대응 프록시/IP 회전 모듈."""

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict

logger = logging.getLogger("facebook.proxy_manager")


@dataclass
class ProxyInfo:
    """프록시 정보."""
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    protocol: str = "http"  # "http" | "socks5"
    # 상태 추적
    fail_count: int = 0
    success_count: int = 0
    last_used_at: Optional[datetime] = None
    last_failed_at: Optional[datetime] = None
    is_banned: bool = False
    ban_until: Optional[datetime] = None

    @property
    def url(self) -> str:
        """프록시 URL을 반환합니다."""
        if self.username and self.password:
            return f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.protocol}://{self.host}:{self.port}"

    @property
    def playwright_proxy(self) -> Dict:
        """Playwright 프록시 설정 딕셔너리를 반환합니다."""
        config = {"server": f"{self.protocol}://{self.host}:{self.port}"}
        if self.username:
            config["username"] = self.username
        if self.password:
            config["password"] = self.password
        return config

    @property
    def is_available(self) -> bool:
        """프록시 사용 가능 여부."""
        if self.is_banned:
            if self.ban_until and datetime.now() > self.ban_until:
                self.is_banned = False
                self.ban_until = None
                return True
            return False
        return True

    @property
    def fail_rate(self) -> float:
        """실패율 (0.0 ~ 1.0)."""
        total = self.fail_count + self.success_count
        if total == 0:
            return 0.0
        return self.fail_count / total


@dataclass
class ProxyRotationConfig:
    """프록시 회전 설정."""
    # 차단 감지 임계값
    consecutive_fail_threshold: int = 3    # 연속 실패 N번이면 차단으로 판단
    fail_rate_threshold: float = 0.5       # 실패율 50% 초과시 차단 의심
    # 차단 후 대기
    ban_duration_minutes: int = 30         # 차단 프록시 재시도 대기 시간
    # 회전 전략
    rotation_strategy: str = "random"      # "random" | "round_robin" | "least_used"
    # 요청 간격
    min_request_interval: float = 2.0      # 동일 프록시 최소 재사용 간격 (초)


class ProxyManager:
    """Facebook 크롤링용 프록시 관리자.

    Facebook은 IP 차단이 강하므로 프록시 회전이 필수입니다.

    사용법:
        manager = ProxyManager()
        manager.add_proxy("1.2.3.4", 8080)
        proxy = manager.get_next_proxy()
        if proxy:
            # Playwright에 프록시 설정
            context = await browser.new_context(proxy=proxy.playwright_proxy)
    """

    def __init__(self, config: Optional[ProxyRotationConfig] = None):
        self.config = config or ProxyRotationConfig()
        self._proxies: List[ProxyInfo] = []
        self._round_robin_index: int = 0
        self._consecutive_fails: Dict[str, int] = {}  # proxy_url -> fail count

    def add_proxy(
        self,
        host: str,
        port: int,
        username: Optional[str] = None,
        password: Optional[str] = None,
        protocol: str = "http",
    ):
        """프록시를 추가합니다."""
        proxy = ProxyInfo(
            host=host,
            port=port,
            username=username,
            password=password,
            protocol=protocol,
        )
        self._proxies.append(proxy)
        logger.info(f"프록시 추가: {proxy.host}:{proxy.port}")

    def add_proxies_from_list(self, proxy_list: List[Dict]):
        """딕셔너리 목록으로 프록시를 일괄 추가합니다.

        Args:
            proxy_list: [{"host": "...", "port": 8080, "username": "...", "password": "..."}, ...]
        """
        for p in proxy_list:
            self.add_proxy(
                host=p["host"],
                port=p["port"],
                username=p.get("username"),
                password=p.get("password"),
                protocol=p.get("protocol", "http"),
            )

    @property
    def available_proxies(self) -> List[ProxyInfo]:
        """사용 가능한 프록시 목록."""
        return [p for p in self._proxies if p.is_available]

    def get_next_proxy(self) -> Optional[ProxyInfo]:
        """다음 사용할 프록시를 반환합니다.

        Returns:
            ProxyInfo 또는 None (사용 가능한 프록시 없음)
        """
        available = self.available_proxies
        if not available:
            logger.warning("사용 가능한 프록시 없음")
            return None

        strategy = self.config.rotation_strategy

        if strategy == "round_robin":
            proxy = available[self._round_robin_index % len(available)]
            self._round_robin_index += 1
        elif strategy == "least_used":
            proxy = min(available, key=lambda p: p.success_count + p.fail_count)
        else:
            # random (기본)
            proxy = random.choice(available)

        proxy.last_used_at = datetime.now()
        return proxy

    def report_success(self, proxy: ProxyInfo):
        """프록시 성공을 보고합니다."""
        proxy.success_count += 1
        key = proxy.url
        self._consecutive_fails[key] = 0
        logger.debug(f"프록시 성공: {proxy.host}:{proxy.port} (total={proxy.success_count})")

    def report_failure(self, proxy: ProxyInfo, is_blocked: bool = False):
        """프록시 실패를 보고합니다.

        Args:
            proxy: 실패한 프록시
            is_blocked: IP 차단 감지 여부
        """
        proxy.fail_count += 1
        proxy.last_failed_at = datetime.now()
        key = proxy.url
        self._consecutive_fails[key] = self._consecutive_fails.get(key, 0) + 1

        consecutive = self._consecutive_fails[key]

        if is_blocked or consecutive >= self.config.consecutive_fail_threshold:
            self._ban_proxy(proxy)
        elif proxy.fail_rate > self.config.fail_rate_threshold:
            logger.warning(
                f"프록시 실패율 높음: {proxy.host}:{proxy.port} "
                f"(실패율={proxy.fail_rate:.0%}, 연속={consecutive})"
            )

    def _ban_proxy(self, proxy: ProxyInfo):
        """프록시를 일시 차단 처리합니다."""
        proxy.is_banned = True
        proxy.ban_until = datetime.now() + timedelta(minutes=self.config.ban_duration_minutes)
        logger.warning(
            f"프록시 차단 처리: {proxy.host}:{proxy.port} "
            f"(해제 예정: {proxy.ban_until.strftime('%H:%M')})"
        )

    def get_status(self) -> Dict:
        """프록시 풀 현황을 반환합니다."""
        total = len(self._proxies)
        available = len(self.available_proxies)
        banned = total - available
        return {
            "total": total,
            "available": available,
            "banned": banned,
            "proxies": [
                {
                    "host": p.host,
                    "port": p.port,
                    "available": p.is_available,
                    "success": p.success_count,
                    "fail": p.fail_count,
                    "fail_rate": f"{p.fail_rate:.0%}",
                    "banned": p.is_banned,
                    "ban_until": p.ban_until.isoformat() if p.ban_until else None,
                }
                for p in self._proxies
            ],
        }

    def detect_block_from_page(self, page_content: str) -> bool:
        """페이지 내용으로 IP 차단 여부를 감지합니다.

        Args:
            page_content: 페이지 HTML 또는 텍스트

        Returns:
            True면 차단 감지
        """
        block_signals = [
            "You're Temporarily Blocked",
            "temporarily blocked",
            "captcha",
            "CAPTCHA",
            "checkpoint",
            "suspicious activity",
            "unusual activity",
            "로그인이 필요합니다",  # 로그인 세션 만료
        ]
        content_lower = page_content.lower()
        for signal in block_signals:
            if signal.lower() in content_lower:
                logger.warning(f"IP 차단 신호 감지: '{signal}'")
                return True
        return False
