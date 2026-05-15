"""Anonymous POPPLY reservation API client."""

from __future__ import annotations

import aiohttp


class PopplyHttpClient:
    BASE_URL = "https://api.popply.co.kr/api/store"

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds

    async def fetch_reservation(self, store_id: str, reservation_type: str = "PRE") -> dict:
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        url = f"{self.BASE_URL}/{store_id}/reservation"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params={"type": reservation_type}) as response:
                if response.status != 200:
                    text = await response.text()
                    raise RuntimeError(f"POPPLY API status={response.status}: {text[:200]}")
                return await response.json()
