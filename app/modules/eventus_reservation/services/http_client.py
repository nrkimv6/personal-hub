"""Eventus anonymous HTML fetcher."""

from __future__ import annotations

import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class EventusHttpClient:
    """Anonymous HTTP client for Eventus event HTML pages."""

    def __init__(
        self,
        timeout: Optional[aiohttp.ClientTimeout] = None,
        headers: Optional[dict] = None,
    ):
        self._timeout = timeout or _TIMEOUT
        self._headers = {**_DEFAULT_HEADERS, **(headers or {})}

    async def fetch_event_page(self, url: str) -> str:
        """Fetch Eventus event page HTML.

        Returns:
            Raw HTML text (UTF-8).

        Raises:
            RuntimeError: If response status is not 200.
        """
        async with aiohttp.ClientSession(
            headers=self._headers,
            timeout=self._timeout,
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Eventus HTTP {resp.status}: {url}")
                return await resp.text(encoding="utf-8", errors="replace")
