"""Shared helpers for live HTTP tests that run against localhost services."""

from __future__ import annotations

import time

import httpx
import pytest

ADMIN_BASE_URL = "http://localhost:8001"
LIVENESS_PATH = "/api/v1/system/liveness"


def wait_until_live_api_ready(
    *,
    base_url: str = ADMIN_BASE_URL,
    timeout_seconds: float = 45.0,
    label: str = "admin API",
) -> None:
    """Wait until the live admin API is reachable after service restart tests."""

    deadline = time.time() + max(timeout_seconds, 1.0)
    last_error: str | None = None
    url = f"{base_url}{LIVENESS_PATH}"
    while time.time() <= deadline:
        try:
            response = httpx.get(url, timeout=5)
            if response.status_code == 200:
                payload = response.json()
                if payload.get("status") in {None, "ok"}:
                    return
                last_error = f"unexpected liveness payload: {payload}"
            else:
                last_error = f"unexpected status: {response.status_code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)

    pytest.fail(f"{label} did not become ready: {url} ({last_error})")


def live_get_after_readiness(path: str, *, base_url: str = ADMIN_BASE_URL) -> httpx.Response:
    deadline = time.time() + 45.0
    url = f"{base_url}{path}"
    last_error: str | None = None

    while time.time() <= deadline:
        wait_until_live_api_ready(base_url=base_url)
        try:
            return httpx.get(url, timeout=15)
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_error = str(exc)
            time.sleep(1)

    pytest.fail(f"실서버 미기동 또는 restart settle 미완료 — {url} 응답 실패 ({last_error})")
