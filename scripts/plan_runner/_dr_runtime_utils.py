"""Shared runtime helpers for dev-runner execution paths.

This module centralizes exit-reason normalization and Redis publish retry
semantics so listener/runtime code paths cannot drift.
"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject


from typing import Optional

import redis


def _normalize_exit_reason(reason: Optional[str]) -> str:
    """Normalize exit reason into the UI/runtime contract token."""
    norm = (reason or "error").strip().lower()
    if norm == "rate_limited":
        return "rate_limit"
    return norm or "error"


def _publish_with_retry(redis_client: redis.Redis, channel: str, msg: str) -> bool:
    """Publish once, then retry after ping on connection errors."""
    try:
        redis_client.publish(channel, msg)
        return True
    except redis.ConnectionError:
        pass

    try:
        redis_client.ping()
        redis_client.publish(channel, msg)
        return True
    except (redis.ConnectionError, Exception):
        return False

