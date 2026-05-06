"""Relay GUI open requests from Session 0 to a user-session worker."""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Sequence

import redis.asyncio as aioredis

from app.core.config import settings
from app.shared.process import session
from app.shared.redis.queue import OPEN_APP_COMMAND_QUEUE

logger = logging.getLogger(__name__)

ALLOWED_OPEN_APPS = {"explorer", "code", "default"}


class OpenAppRelayError(RuntimeError):
    """Raised when an open-app request cannot be safely dispatched."""


async def relay_open_app(app_name: str, args: Sequence[str]) -> dict:
    """Open a GUI app directly in user sessions or enqueue it from Session 0.

    Session 0 callers must not create GUI subprocesses because Windows will
    launch them in the service desktop where users cannot see them.
    """
    normalized_app = _normalize_app_name(app_name)
    normalized_args = [str(arg) for arg in args]

    if session.is_session_0():
        await _enqueue_open_app(normalized_app, normalized_args)
        return {"via": "redis", "app": normalized_app}

    _popen_open_app(normalized_app, normalized_args)
    return {"via": "direct", "app": normalized_app}


def _normalize_app_name(app_name: str) -> str:
    normalized = str(app_name or "").strip().lower()
    if normalized not in ALLOWED_OPEN_APPS:
        raise OpenAppRelayError(f"지원하지 않는 open app입니다: {app_name}")
    return normalized


async def _enqueue_open_app(app_name: str, args: list[str]) -> None:
    payload = json.dumps({"app_name": app_name, "args": args}, ensure_ascii=False)
    client = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
        socket_connect_timeout=5,
    )
    try:
        await client.lpush(OPEN_APP_COMMAND_QUEUE, payload)
        logger.info("Open app Redis relay queued: app=%s args=%s", app_name, args)
    except Exception as exc:
        logger.warning("Open app Redis relay failed: app=%s error=%s", app_name, exc)
        raise OpenAppRelayError("Session 0에서 GUI 열기 요청을 Redis 워커에 위임하지 못했습니다.") from exc
    finally:
        await client.aclose()


def _popen_open_app(app_name: str, args: Sequence[str]) -> None:
    if app_name == "default":
        command = ["cmd", "/c", "start", "", *args]
    else:
        command = [app_name, *args]

    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
