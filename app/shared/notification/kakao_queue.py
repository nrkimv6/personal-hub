"""Kakao notification queue helpers.

Kakao 발송은 Redis List에 적재한 뒤 Session 1 전용 소비자가 처리합니다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.config import settings
from app.shared.redis.queue import KAKAO_NOTIFICATION_QUEUE, RedisQueue

logger = logging.getLogger(__name__)

KAKAO_BACKLOG_ALERT_KEY = "notification:kakao:backlog-alert"
KAKAO_DEDUP_KEY_PREFIX = "notification:kakao:dedup"
KAKAO_DEAD_LETTER_QUEUE = "notification:kakao:dead-letter"


def get_kakao_queue_name() -> str:
    """Redis에 실제 저장되는 카카오 큐 이름을 반환합니다."""
    prefix = getattr(settings, "REDIS_QUEUE_PREFIX", "monitor")
    return f"{prefix}:{KAKAO_NOTIFICATION_QUEUE}"


def get_kakao_backlog_alert_key() -> str:
    """카카오 backlog 경고용 cooldown 키를 반환합니다."""
    prefix = getattr(settings, "REDIS_QUEUE_PREFIX", "monitor")
    return f"{prefix}:{KAKAO_BACKLOG_ALERT_KEY}"


def get_kakao_dead_letter_queue_name() -> str:
    """Redis에 실제 저장되는 카카오 dead-letter 큐 이름을 반환합니다."""
    prefix = getattr(settings, "REDIS_QUEUE_PREFIX", "monitor")
    return f"{prefix}:{KAKAO_DEAD_LETTER_QUEUE}"


def normalize_kakao_metadata(metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Kakao payload metadata 기본 계약을 채웁니다."""
    normalized = dict(metadata or {})
    normalized.setdefault("retry_count", 0)
    normalized.setdefault("last_error", None)
    normalized.setdefault("guard_required", True)
    return normalized


def build_kakao_payload(
    message: str,
    room_name: str,
    *,
    source: str,
    metadata: Optional[dict[str, Any]] = None,
    expires_seconds: Optional[int] = None,
) -> dict[str, Any]:
    """큐에 넣을 payload를 생성합니다."""
    now = datetime.now()
    expires_in = expires_seconds or getattr(settings, "MEGABEAUTY_KAKAO_ALERT_EXPIRES_SECONDS", 900)
    expires_at = now + timedelta(seconds=expires_in)

    payload = {
        "id": uuid.uuid4().hex,
        "message": message,
        "room_name": room_name,
        "source": source,
        "created_at": now.isoformat(timespec="seconds"),
        "expires_at": expires_at.isoformat(timespec="seconds"),
        "metadata": normalize_kakao_metadata(metadata),
    }
    return payload


def build_kakao_dedup_key(room_name: str, message: str, metadata: Optional[dict[str, Any]] = None) -> str:
    """동일 Kakao payload 중복 억제를 위한 Redis 키를 생성합니다."""
    stable = {
        "room_name": room_name,
        "message": message,
        "metadata": metadata or {},
    }
    digest = hashlib.sha256(
        json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    prefix = getattr(settings, "REDIS_QUEUE_PREFIX", "monitor")
    return f"{prefix}:{KAKAO_DEDUP_KEY_PREFIX}:{digest}"


def is_payload_expired(payload: dict[str, Any]) -> bool:
    """payload 만료 여부를 판정합니다."""
    expires_at = payload.get("expires_at")
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) < datetime.now()
    except Exception:
        logger.warning("카카오 payload 만료 시각 파싱 실패: %r", expires_at)
        return True


class KakaoNotificationQueue:
    """카카오 알림용 Redis List 큐 래퍼."""

    def __init__(self, client: aioredis.Redis, room_name: Optional[str] = None):
        self.client = client
        self.room_name = room_name or getattr(settings, "MEGABEAUTY_KAKAO_ALERT_ROOM_NAME", "소나무봇")
        self._queue = RedisQueue(client, KAKAO_NOTIFICATION_QUEUE)
        self._dead_letter_queue = RedisQueue(client, KAKAO_DEAD_LETTER_QUEUE)

    @property
    def queue_name(self) -> str:
        return self._queue.queue_name

    async def enqueue(
        self,
        message: str,
        *,
        source: str,
        metadata: Optional[dict[str, Any]] = None,
        expires_seconds: Optional[int] = None,
        dedup_ttl_seconds: Optional[int] = None,
    ) -> dict[str, Any]:
        """메시지를 큐에 적재합니다.

        Returns:
            dict: enqueued / duplicate / queue_length / payload 포함 결과
        """
        if not bool(getattr(settings, "MEGABEAUTY_KAKAO_ALERT_ENABLED", False)):
            return {
                "enqueued": False,
                "duplicate": False,
                "disabled": True,
                "queue_length": 0,
                "payload": None,
            }

        dedup_key = build_kakao_dedup_key(self.room_name, message, metadata)
        dedup_ttl = dedup_ttl_seconds or getattr(settings, "MEGABEAUTY_KAKAO_ALERT_DEDUP_TTL_SECONDS", 300)
        try:
            accepted = await self.client.set(dedup_key, "1", ex=dedup_ttl, nx=True)
            if not accepted:
                return {
                    "enqueued": False,
                    "duplicate": True,
                    "disabled": False,
                    "queue_length": await self._safe_length(),
                    "payload": None,
                }

            payload = build_kakao_payload(
                message,
                self.room_name,
                source=source,
                metadata=metadata,
                expires_seconds=expires_seconds,
            )
            pushed = await self._queue.push(payload)
            if not pushed:
                logger.warning("카카오 큐 적재 실패: %s", self.queue_name)
                return {
                    "enqueued": False,
                    "duplicate": False,
                    "disabled": False,
                    "queue_length": await self._safe_length(),
                    "payload": payload,
                }

            return {
                "enqueued": True,
                "duplicate": False,
                "disabled": False,
                "queue_length": await self._safe_length(),
                "payload": payload,
            }
        except Exception as e:
            logger.warning("카카오 큐 적재 중 오류: %s", e)
            return {
                "enqueued": False,
                "duplicate": False,
                "disabled": False,
                "queue_length": 0,
                "payload": None,
                "error": str(e),
            }

    async def pop(self, timeout: int = 0) -> Optional[dict[str, Any]]:
        """큐에서 다음 payload를 꺼냅니다."""
        return await self._queue.pop(timeout=timeout)

    async def length(self) -> int:
        """큐 길이를 반환합니다."""
        return await self._queue.length()

    async def peek(self, count: int = 10) -> list[dict[str, Any]]:
        """큐 앞부분을 확인합니다."""
        return await self._queue.peek(count=count)

    async def requeue(self, payload: dict[str, Any], *, last_error: str) -> bool:
        """retryable 실패 payload를 retry metadata와 함께 원본 큐에 다시 넣습니다."""
        updated = dict(payload)
        metadata = normalize_kakao_metadata(updated.get("metadata"))
        metadata["retry_count"] = int(metadata.get("retry_count") or 0) + 1
        metadata["last_error"] = last_error
        metadata["last_retry_at"] = datetime.now().isoformat(timespec="seconds")
        updated["metadata"] = metadata
        return await self._queue.push(updated)

    async def dead_letter(self, payload: dict[str, Any], *, last_error: str) -> bool:
        """비복구/재시도 초과 payload를 dead-letter 큐에 보존합니다."""
        updated = dict(payload or {})
        metadata = normalize_kakao_metadata(updated.get("metadata"))
        metadata["last_error"] = last_error
        metadata["dead_lettered_at"] = datetime.now().isoformat(timespec="seconds")
        updated["metadata"] = metadata
        return await self._dead_letter_queue.push(updated)

    async def dead_letter_length(self) -> int:
        """dead-letter 큐 길이를 반환합니다."""
        return await self._dead_letter_queue.length()

    async def dead_letter_peek(self, count: int = 10) -> list[dict[str, Any]]:
        """dead-letter 큐 앞부분을 확인합니다."""
        return await self._dead_letter_queue.peek(count=count)

    async def _safe_length(self) -> int:
        try:
            return await self.length()
        except Exception:
            return 0
