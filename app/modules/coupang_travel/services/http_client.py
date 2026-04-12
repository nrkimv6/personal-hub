"""
쿠팡 여행상품 vendor-items aiohttp 클라이언트.

네이버 GraphQL 클라이언트(graphql_client.py)와 동일한 ProxyManager 패턴 적용:
- 요청마다 get_fresh_proxy() → 실패 시 mark_failed() + 다음 프록시 재시도
- 세션 쿠키는 상품 페이지 GET 시 aiohttp cookie_jar가 자동 관리
- ProxyUsageLogger로 모든 시도 이력 기록

Playwright fallback: 워커가 이 클라이언트 실패 시 기존 브라우저 경로로 fallback.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Optional, TYPE_CHECKING
from urllib.parse import urlparse

import aiohttp
try:
    from aiohttp_socks import ProxyConnector as _SocksProxyConnector
    _SOCKS_AVAILABLE = True
except ImportError:
    _SocksProxyConnector = None
    _SOCKS_AVAILABLE = False

from app.modules.coupang_travel.services.api_client import VendorItem

if TYPE_CHECKING:
    from app.services.proxy_manager import ProxyManager
    from app.services.proxy_usage_logger import ProxyUsageLogger

logger = logging.getLogger(__name__)

_BASE_URL = "https://trip.coupang.com"
_VENDOR_ITEMS_PATH = "/api/products/{product_id}/vendor-items"
_PRODUCT_PAGE_PATH = "/tp/products/{product_id}"

# 타임아웃
_PROXY_TIMEOUT = 5.0       # 프록시 경유 시 (프록시 자체가 느릴 수 있음)
_DIRECT_TIMEOUT = 30.0     # 직접 연결 시

# 최대 재시도
_MAX_RETRIES = 5


class CoupangHttpClient:
    """
    aiohttp 기반 쿠팡 vendor-items 클라이언트.

    네이버 예약과 동일한 요청 단위 프록시 로테이션을 지원한다.
    브라우저 없이 동작하며, 세션 쿠키는 상품 페이지 첫 방문 시 자동 획득한다.
    """

    def __init__(
        self,
        proxy_manager: Optional["ProxyManager"] = None,
        proxy_usage_logger: Optional["ProxyUsageLogger"] = None,
    ):
        """
        Args:
            proxy_manager: 프록시 매니저 (없으면 직접 연결)
            proxy_usage_logger: 프록시 사용 이력 로거 (없으면 기록 생략)
        """
        self._proxy_manager = proxy_manager
        self._usage_logger = proxy_usage_logger
        self._session: Optional[aiohttp.ClientSession] = None
        # 쿠키가 이미 획득됐는지 추적 (product_id별)
        self._cookie_initialized: set = set()

    @staticmethod
    def _is_socks_proxy(proxy_url: Optional[str]) -> bool:
        """SOCKS4/SOCKS5 프록시 여부 확인."""
        if not proxy_url:
            return False
        return proxy_url.startswith(("socks4://", "socks5://", "socks4a://"))

    async def _make_session(self, proxy_url: Optional[str] = None) -> aiohttp.ClientSession:
        """
        프록시 타입에 맞는 세션 반환.
        - SOCKS 프록시: ProxyConnector 포함 임시 세션 (매 호출 신규 생성)
        - HTTP 프록시 / 직접 연결: 재사용 세션
        """
        headers = {
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        if self._is_socks_proxy(proxy_url):
            if not _SOCKS_AVAILABLE:
                raise RuntimeError("aiohttp-socks가 설치되지 않아 SOCKS 프록시를 사용할 수 없습니다.")
            connector = _SocksProxyConnector.from_url(proxy_url, ssl=False)
            return aiohttp.ClientSession(connector=connector, headers=headers)
        # HTTP 프록시 또는 직접 연결: 재사용 세션
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(connector=connector, headers=headers)
        return self._session

    async def _ensure_cookies(self, product_id: str, proxy_url: Optional[str] = None) -> None:
        """
        상품 페이지를 GET하여 세션 쿠키 획득.

        aiohttp.ClientSession의 cookie_jar가 Set-Cookie를 자동 저장하므로
        이후 POST 요청에 자동으로 포함된다.
        이미 쿠키를 획득한 product_id면 스킵.
        """
        if product_id in self._cookie_initialized:
            return

        url = f"{_BASE_URL}{_PRODUCT_PAGE_PATH.format(product_id=product_id)}"
        timeout = aiohttp.ClientTimeout(total=_PROXY_TIMEOUT if proxy_url else _DIRECT_TIMEOUT)
        is_socks = self._is_socks_proxy(proxy_url)
        session = await self._make_session(proxy_url)
        # SOCKS 세션은 close가 필요하므로 컨텍스트 관리
        close_session = is_socks

        try:
            # SOCKS: proxy_url은 이미 커넥터에 포함되므로 proxy 파라미터 불필요
            request_proxy = None if is_socks else proxy_url
            async with session.get(url, proxy=request_proxy, timeout=timeout, allow_redirects=True) as resp:
                logger.debug(
                    "[CoupangHttpClient] 쿠키 획득 GET %s → HTTP %d (proxy=%s)",
                    url, resp.status, proxy_url,
                )
                # 상태 코드와 무관하게 cookie_jar에 쿠키가 설정됨
                self._cookie_initialized.add(product_id)
        except Exception as e:
            logger.warning("[CoupangHttpClient] 쿠키 획득 실패: %s", e)
            # 실패해도 진행 — 쿠키 없이도 vendor-items API가 응답하는지 시도
        finally:
            if close_session and not session.closed:
                await session.close()

    async def fetch_vendor_items(
        self,
        product_id: str,
        vendor_item_package_id: str,
        select_date: str,
        schedule_id: Optional[int] = None,
    ) -> Optional[List[VendorItem]]:
        """
        vendor-items API를 aiohttp로 호출. 프록시 로테이션 적용.

        Args:
            product_id: 쿠팡 상품 ID
            vendor_item_package_id: 벤더 아이템 패키지 ID
            select_date: 조회 날짜 (YYYY-MM-DD)
            schedule_id: 프록시 사용 이력 기록용

        Returns:
            VendorItem 리스트, 전체 실패 시 None
        """
        url = f"{_BASE_URL}{_VENDOR_ITEMS_PATH.format(product_id=product_id)}"
        referer = f"{_BASE_URL}{_PRODUCT_PAGE_PATH.format(product_id=product_id)}"

        body = {
            "vendorItemPackageId": vendor_item_package_id,
            "productType": "TICKET",
            "selectDate": select_date,
        }
        headers = {
            "origin": _BASE_URL,
            "referer": referer,
            "content-type": "application/json;charset=UTF-8",
        }

        # 프록시 사용 이력 요청 시작
        usage_request_id: Optional[str] = None
        if self._usage_logger and schedule_id:
            usage_request_id = self._usage_logger.start_request(
                schedule_id=schedule_id,
                target_url=url,
                fetch_method="coupang_http_api",
            )

        tried_proxies: set = set()
        last_error: Optional[str] = None

        # 쿠키 획득 1회 (직접 연결) — 루프 밖에서 미리 수행하여 프록시당 1 POST만 실행
        await self._ensure_cookies(product_id, proxy_url=None)

        for attempt in range(_MAX_RETRIES + 1):
            proxy_url: Optional[str] = None
            if self._proxy_manager:
                proxy_url = self._proxy_manager.get_fresh_proxy(exclude=tried_proxies)
                if proxy_url:
                    tried_proxies.add(proxy_url)
                if attempt == 0:
                    logger.debug("[CoupangHttpClient] 프록시 사용: %s", proxy_url)
                else:
                    logger.info(
                        "[CoupangHttpClient] 재시도 #%d/%d — 프록시: %s",
                        attempt, _MAX_RETRIES, proxy_url,
                    )

            timeout = aiohttp.ClientTimeout(
                total=_PROXY_TIMEOUT if proxy_url else _DIRECT_TIMEOUT
            )
            request_start = time.time()
            is_socks = self._is_socks_proxy(proxy_url)
            request_session = await self._make_session(proxy_url)
            # SOCKS 세션은 요청 후 닫아야 함
            close_after = is_socks

            try:
                # SOCKS: proxy_url은 커넥터에 포함됨, HTTP: proxy 파라미터로 전달
                request_proxy = None if is_socks else proxy_url
                async with request_session.post(
                    url,
                    json=body,
                    headers=headers,
                    proxy=request_proxy,
                    timeout=timeout,
                ) as resp:
                    response_time = time.time() - request_start

                    if resp.status in (403, 429) and proxy_url and self._proxy_manager:
                        logger.warning(
                            "[CoupangHttpClient] HTTP %d — 프록시 실패: %s",
                            resp.status, proxy_url,
                        )
                        self._proxy_manager.mark_failed(proxy_url, f"HTTP {resp.status}")
                        last_error = f"HTTP {resp.status}"
                        if usage_request_id:
                            self._usage_logger.log_attempt(
                                request_id=usage_request_id,
                                proxy_url=proxy_url,
                                success=False,
                                http_status=resp.status,
                                error_type=f"http_{resp.status}",
                                response_time_ms=int(response_time * 1000),
                            )
                        continue  # 다음 프록시로

                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")

                    data = await resp.json(content_type=None)
                    items = _parse_vendor_items(data)

                    if usage_request_id:
                        self._usage_logger.log_attempt(
                            request_id=usage_request_id,
                            proxy_url=proxy_url or "direct",
                            success=True,
                            http_status=200,
                            response_time_ms=int(response_time * 1000),
                        )

                    logger.debug(
                        "[CoupangHttpClient] 성공 (attempt=%d, proxy=%s, items=%d)",
                        attempt, proxy_url, len(items),
                    )
                    return items

            except asyncio.TimeoutError:
                response_time = time.time() - request_start
                last_error = "timeout"
                if proxy_url and self._proxy_manager:
                    self._proxy_manager.mark_failed(proxy_url, "timeout")
                if usage_request_id and proxy_url:
                    self._usage_logger.log_attempt(
                        request_id=usage_request_id,
                        proxy_url=proxy_url,
                        success=False,
                        error_type="timeout",
                        response_time_ms=int(response_time * 1000),
                    )
                logger.warning(
                    "[CoupangHttpClient] 타임아웃 (attempt=%d, proxy=%s)",
                    attempt, proxy_url,
                )

            except Exception as e:
                response_time = time.time() - request_start
                last_error = str(e)[:80]
                if proxy_url and self._proxy_manager:
                    self._proxy_manager.mark_failed(proxy_url, last_error)
                if usage_request_id and proxy_url:
                    self._usage_logger.log_attempt(
                        request_id=usage_request_id,
                        proxy_url=proxy_url,
                        success=False,
                        error_type="exception",
                        error_message=last_error,
                        response_time_ms=int(response_time * 1000),
                    )
                logger.warning(
                    "[CoupangHttpClient] 요청 실패 (attempt=%d, proxy=%s): %s",
                    attempt, proxy_url, e,
                )

            finally:
                if close_after and not request_session.closed:
                    await request_session.close()

        # 프록시 전체 실패 후 직접 연결 1회 시도
        if self._proxy_manager:
            logger.warning("[CoupangHttpClient] 모든 프록시 실패 — 직접 연결(direct) 시도")
            await self._ensure_cookies(product_id, proxy_url=None)
            timeout = aiohttp.ClientTimeout(total=_DIRECT_TIMEOUT)
            request_session = await self._make_session(proxy_url=None)
            request_start = time.time()
            try:
                async with request_session.post(
                    url, json=body, headers=headers, proxy=None, timeout=timeout
                ) as resp:
                    response_time = time.time() - request_start
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        items = _parse_vendor_items(data)
                        if usage_request_id:
                            self._usage_logger.log_attempt(
                                request_id=usage_request_id,
                                proxy_url="direct",
                                success=True,
                                http_status=200,
                                response_time_ms=int(response_time * 1000),
                            )
                        logger.info("[CoupangHttpClient] 직접 연결 성공 (items=%d)", len(items))
                        return items
                    else:
                        text = await resp.text()
                        last_error = f"direct HTTP {resp.status}: {text[:100]}"
                        logger.warning("[CoupangHttpClient] 직접 연결 실패: %s", last_error)
            except Exception as e:
                last_error = str(e)[:80]
                logger.warning("[CoupangHttpClient] 직접 연결 예외: %s", e)

        logger.error(
            "[CoupangHttpClient] 최대 재시도 초과 (product_id=%s, date=%s, last_error=%s)",
            product_id, select_date, last_error,
        )
        return None

    async def close(self) -> None:
        """세션 종료."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


def _parse_vendor_items(data: dict) -> List[VendorItem]:
    """API 응답에서 VendorItem 리스트 추출. api_client._parse_vendor_items와 동일 로직."""
    items: List[VendorItem] = []
    travel_items = data.get("travelItems") or []
    for travel in travel_items:
        for vi in travel.get("vendorItems") or []:
            items.append(
                VendorItem(
                    vendor_item_name=vi.get("vendorItemName", ""),
                    sale_status=vi.get("saleStatus", ""),
                    stock_count=vi.get("stockCount", 0),
                )
            )
    return items
