"""Shared SSE initial status collection helpers for live filter tests."""

from collections.abc import Callable, Iterable
import json
import os
import time
from typing import Any

import requests

SSE_INITIAL_STATUS_MAX_RETRIES_ENV = "SSE_INITIAL_STATUS_MAX_RETRIES"
SSE_INITIAL_STATUS_RETRY_DELAY_ENV = "SSE_INITIAL_STATUS_RETRY_DELAY"
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 2.0


def collect_initial_status_with_retry(
    url: str,
    *,
    timeout: float = 5.0,
    max_retries: int | None = None,
    retry_delay: float | None = None,
    require_status_code: int | None = None,
    request_get: Callable[..., Any] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    environ: dict[str, str] | None = None,
) -> list[dict]:
    """Return the first SSE status event's runners, retrying setup failures.

    A status event with an empty runners list is a valid filter result and is
    returned immediately. Retries are reserved for connection failures or a
    stream that ends/times out before any status event arrives.
    """
    max_retries = _resolve_positive_int(
        max_retries,
        env_name=SSE_INITIAL_STATUS_MAX_RETRIES_ENV,
        default=DEFAULT_MAX_RETRIES,
        environ=environ,
    )
    retry_delay = _resolve_non_negative_float(
        retry_delay,
        env_name=SSE_INITIAL_STATUS_RETRY_DELAY_ENV,
        default=DEFAULT_RETRY_DELAY,
        environ=environ,
    )

    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")

    for attempt in range(max_retries):
        try:
            found_status, runners = _collect_initial_status_once(
                url,
                timeout=timeout,
                require_status_code=require_status_code,
                request_get=request_get,
                monotonic=monotonic,
            )
        except (json.JSONDecodeError, requests.RequestException):
            found_status, runners = False, []

        if found_status:
            return runners
        if attempt < max_retries - 1:
            sleep(retry_delay)

    return []


def _resolve_positive_int(
    value: int | None,
    *,
    env_name: str,
    default: int,
    environ: dict[str, str] | None,
) -> int:
    if value is not None:
        return value
    source = os.environ if environ is None else environ
    raw_value = source.get(env_name)
    if raw_value is None:
        return default
    parsed = int(raw_value)
    if parsed < 1:
        raise ValueError(f"{env_name} must be at least 1")
    return parsed


def _resolve_non_negative_float(
    value: float | None,
    *,
    env_name: str,
    default: float,
    environ: dict[str, str] | None,
) -> float:
    if value is not None:
        return value
    source = os.environ if environ is None else environ
    raw_value = source.get(env_name)
    if raw_value is None:
        return default
    parsed = float(raw_value)
    if parsed < 0:
        raise ValueError(f"{env_name} must be non-negative")
    return parsed


def _collect_initial_status_once(
    url: str,
    *,
    timeout: float,
    require_status_code: int | None,
    request_get: Callable[..., Any],
    monotonic: Callable[[], float],
) -> tuple[bool, list[dict]]:
    with request_get(url, stream=True, timeout=timeout + 1) as resp:
        if require_status_code is not None:
            assert resp.status_code == require_status_code, (
                f"GET /events HTTP {resp.status_code}"
            )

        current_event = "message"
        deadline = monotonic() + timeout
        for raw_line in _iter_sse_lines(resp):
            if monotonic() > deadline:
                break
            if not raw_line:
                current_event = "message"
                continue
            if raw_line.startswith("event:"):
                current_event = raw_line[6:].strip()
            elif raw_line.startswith("data:") and current_event == "status":
                data = json.loads(raw_line[5:].strip())
                return True, data.get("runners", [])

    return False, []


def _iter_sse_lines(resp: Any) -> Iterable[str]:
    return resp.iter_lines(decode_unicode=True)
