from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import random
from typing import Any

import aiohttp

from app.core.config import settings
from app.modules.naver_popup_monitor.schemas import (
    FallbackStrategyLiteral,
    RequestProfileLiteral,
)

TARGET_URL = "https://pcmap.place.naver.com/popupstore/list"
PROFILE_ORDER: tuple[RequestProfileLiteral, ...] = ("A", "B", "C")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

REQUEST_PROFILE_HEADERS: dict[RequestProfileLiteral, dict[str, str]] = {
    "A": {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Referer": "https://pcmap.place.naver.com/",
    },
    "B": {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9",
    },
    "C": {
        "Accept-Language": "ko-KR,ko;q=0.9",
    },
}


@dataclass
class PopupFetchAttempt:
    profile: RequestProfileLiteral
    status: int | None = None
    final_url: str | None = None
    proxy_url: str | None = None
    error: str | None = None


@dataclass
class PopupFetchResult:
    success: bool
    html: str = ""
    status: int | None = None
    final_url: str | None = None
    request_profile: RequestProfileLiteral | None = None
    proxy_url: str | None = None
    fallback_applied: bool = False
    attempts: list[PopupFetchAttempt] = field(default_factory=list)
    error: str | None = None


def get_headers_for_profile(profile: RequestProfileLiteral) -> dict[str, str]:
    """Return request headers for the selected profile."""
    return dict(REQUEST_PROFILE_HEADERS[profile])


def build_attempt_profiles(
    request_profile: RequestProfileLiteral,
    fallback_strategy: FallbackStrategyLiteral,
    rng: random.Random | None = None,
) -> list[RequestProfileLiteral]:
    """
    Build the profile retry order for one fetch cycle.

    reinforce: selected profile first, then A->B->C ring order.
    random_rotate: random permutation of A/B/C.
    """
    if fallback_strategy == "reinforce":
        start_index = PROFILE_ORDER.index(request_profile)
        return list(PROFILE_ORDER[start_index:] + PROFILE_ORDER[:start_index])

    if fallback_strategy == "random_rotate":
        randomizer = rng or random.Random()
        shuffled = list(PROFILE_ORDER)
        randomizer.shuffle(shuffled)
        return shuffled

    raise ValueError(f"Unsupported fallback strategy: {fallback_strategy}")


class PopupFetcher:
    RETRYABLE_STATUS_CODES = {403, 429, 500, 502, 503, 504}

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        proxy_manager: Any | None = None,
        rng: random.Random | None = None,
    ):
        self._session = session
        self._own_session = session is None
        self._proxy_manager = proxy_manager
        self._rng = rng or random.Random()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(connector=connector)
            self._own_session = True
        return self._session

    async def close(self) -> None:
        if self._session and self._own_session:
            await self._session.close()
            self._session = None

    def _pick_proxy_url(self, tried_proxies: set[str]) -> str | None:
        if not settings.PROXY_ENABLED or self._proxy_manager is None:
            return None
        if not hasattr(self._proxy_manager, "get_fresh_proxy"):
            return None
        try:
            proxy_url = self._proxy_manager.get_fresh_proxy(
                exclude=tried_proxies,
                request_method="get",
            )
        except TypeError:
            proxy_url = self._proxy_manager.get_fresh_proxy(request_method="get")
        except Exception:
            return None

        if proxy_url:
            tried_proxies.add(proxy_url)
        return proxy_url

    async def fetch_popup_html(
        self,
        *,
        url: str = TARGET_URL,
        request_profile: RequestProfileLiteral = "A",
        fallback_strategy: FallbackStrategyLiteral = "reinforce",
        monitor_proxy_enabled: bool = False,
        timeout_seconds: float = 20.0,
    ) -> PopupFetchResult:
        session = await self._ensure_session()
        profile_order = build_attempt_profiles(
            request_profile=request_profile,
            fallback_strategy=fallback_strategy,
            rng=self._rng,
        )
        tried_proxies: set[str] = set()
        attempts: list[PopupFetchAttempt] = []
        last_error: str | None = None

        for index, profile in enumerate(profile_order):
            headers = get_headers_for_profile(profile)
            proxy_url = None
            if monitor_proxy_enabled:
                proxy_url = self._pick_proxy_url(tried_proxies)

            try:
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                async with session.get(
                    url,
                    headers=headers,
                    timeout=timeout,
                    proxy=proxy_url,
                ) as response:
                    html = await response.text(errors="ignore")
                    status = response.status
                    final_url = str(response.url)
                    attempts.append(
                        PopupFetchAttempt(
                            profile=profile,
                            status=status,
                            final_url=final_url,
                            proxy_url=proxy_url,
                        )
                    )

                    if status == 200:
                        return PopupFetchResult(
                            success=True,
                            html=html,
                            status=status,
                            final_url=final_url,
                            request_profile=profile,
                            proxy_url=proxy_url,
                            fallback_applied=index > 0,
                            attempts=attempts,
                        )

                    should_retry = (
                        status in self.RETRYABLE_STATUS_CODES
                        and index < len(profile_order) - 1
                    )
                    if should_retry:
                        await asyncio.sleep(0.2)
                        continue

                    return PopupFetchResult(
                        success=False,
                        html=html,
                        status=status,
                        final_url=final_url,
                        request_profile=profile,
                        proxy_url=proxy_url,
                        fallback_applied=index > 0,
                        attempts=attempts,
                        error=f"HTTP {status}",
                    )
            except Exception as exc:  # pragma: no cover - network failures are environment-specific
                last_error = repr(exc)
                attempts.append(
                    PopupFetchAttempt(
                        profile=profile,
                        proxy_url=proxy_url,
                        error=last_error,
                    )
                )
                if index < len(profile_order) - 1:
                    await asyncio.sleep(0.2)
                    continue

        return PopupFetchResult(
            success=False,
            error=last_error or "unknown fetch error",
            fallback_applied=len(attempts) > 1,
            attempts=attempts,
        )
