"""Kakao notification queue status diagnostic."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import redis.asyncio as aioredis

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.shared.notification.kakao_queue import KakaoNotificationQueue, is_payload_expired

GUARD_STATE_FILE = PROJECT_ROOT / "logs" / "kakao_guard_state.json"


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
        dead_letter_length = await queue.dead_letter_length()
        guard_state = None
        if GUARD_STATE_FILE.exists():
            try:
                guard_state = json.loads(GUARD_STATE_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                guard_state = {"state": "unreadable", "error": str(exc)}
        print(json.dumps({
            "queue_name": queue.queue_name,
            "length": length,
            "dead_letter_length": dead_letter_length,
            "room_name": queue.room_name,
            "guard_state": guard_state,
        }, ensure_ascii=False, indent=2))

        preview = await queue.peek(limit)
        if not preview:
            print("preview: []")
        else:
            print("preview:")
            for item in preview:
                status = "expired" if is_payload_expired(item) else "active"
                metadata = item.get("metadata") or {}
                print(
                    f"- {item.get('id')} | {status} | room={item.get('room_name')} | "
                    f"retry={metadata.get('retry_count', 0)} | last_error={metadata.get('last_error')} | "
                    f"created_at={item.get('created_at')} | message={item.get('message')}"
                )
        dead_letters = await queue.dead_letter_peek(limit)
        if dead_letters:
            print("dead_letter_preview:")
            for item in dead_letters:
                metadata = item.get("metadata") or {}
                print(
                    f"- {item.get('id')} | room={item.get('room_name')} | "
                    f"retry={metadata.get('retry_count', 0)} | last_error={metadata.get('last_error')} | "
                    f"dead_lettered_at={metadata.get('dead_lettered_at')}"
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
