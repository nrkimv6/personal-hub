"""Kakao notification queue status diagnostic."""
from __future__ import annotations

import argparse
import asyncio
import json

import redis.asyncio as aioredis

from app.core.config import settings
from app.shared.notification.kakao_queue import KakaoNotificationQueue, is_payload_expired


def _get_setting(name: str, default):
    return getattr(settings, name, default)


async def _run(limit: int) -> int:
    client = aioredis.Redis(
        host=_get_setting("REDIS_HOST", "localhost"),
        port=_get_setting("REDIS_PORT", 6379),
        decode_responses=True,
    )
    queue = KakaoNotificationQueue(client)
    try:
        length = await queue.length()
        print(json.dumps({
            "queue_name": queue.queue_name,
            "length": length,
            "room_name": queue.room_name,
        }, ensure_ascii=False, indent=2))

        preview = await queue.peek(limit)
        if not preview:
            print("preview: []")
            return 0

        print("preview:")
        for item in preview:
            status = "expired" if is_payload_expired(item) else "active"
            print(
                f"- {item.get('id')} | {status} | room={item.get('room_name')} | "
                f"created_at={item.get('created_at')} | message={item.get('message')}"
            )
        return 0
    finally:
        await client.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Show Kakao notification queue status")
    parser.add_argument("--limit", type=int, default=5, help="Number of queue items to preview")
    args = parser.parse_args()
    return asyncio.run(_run(args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
