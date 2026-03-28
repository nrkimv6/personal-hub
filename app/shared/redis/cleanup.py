"""Redis 좀비 연결 감지 및 정리 유틸리티.

SSE pubsub 누수 방어를 위해 좀비 상태의 Redis 연결을 감지하고 kill한다.

좀비 판정 기준:
- idle > idle_threshold 초
- flags에 'S'(subscriber) 포함 OR cmd가 subscribe/psubscribe/listening
- sub + psub == 0 (활성 구독 채널이 없는 경우만 — SSE 오탐 방지)
"""
import asyncio
import logging
from typing import Optional

import redis.asyncio as aioredis
import redis as syncredis

logger = logging.getLogger(__name__)

_ZOMBIE_CMDS = {"subscribe", "psubscribe", "listening"}


def _is_zombie(conn: dict, idle_threshold: int) -> bool:
    """단일 연결이 좀비인지 판정한다."""
    try:
        idle = int(conn.get("idle", 0))
        flags = conn.get("flags", "")
        cmd = conn.get("cmd", "")
        sub = int(conn.get("sub", 0))
        psub = int(conn.get("psub", 0))
    except (ValueError, TypeError):
        return False

    is_subscriber = "S" in flags or cmd in _ZOMBIE_CMDS
    has_active_channels = sub + psub > 0
    is_idle_too_long = idle > idle_threshold

    return is_subscriber and is_idle_too_long and not has_active_channels


async def get_zombie_connections(
    redis_client: aioredis.Redis,
    idle_threshold: int = 300,
) -> list[dict]:
    """좀비 연결 목록을 반환한다.

    Args:
        redis_client: 연결된 async Redis 클라이언트
        idle_threshold: 이 초 이상 idle이면 좀비 후보

    Returns:
        좀비 연결 dict 목록. 각 항목: {id, addr, idle, cmd, flags, sub, psub}
    """
    connections = await redis_client.client_list()
    zombies = []
    for c in connections:
        if _is_zombie(c, idle_threshold):
            zombies.append({
                "id": c.get("id", ""),
                "addr": c.get("addr", ""),
                "idle": int(c.get("idle", 0)),
                "cmd": c.get("cmd", ""),
                "flags": c.get("flags", ""),
                "sub": int(c.get("sub", 0)),
                "psub": int(c.get("psub", 0)),
            })
    return zombies


async def kill_zombie_connections(
    redis_client: aioredis.Redis,
    idle_threshold: int = 300,
    dry_run: bool = False,
) -> dict:
    """좀비 연결을 감지하고 kill한다.

    Args:
        redis_client: 연결된 async Redis 클라이언트
        idle_threshold: 이 초 이상 idle이면 좀비 후보
        dry_run: True면 실제 kill 없이 카운트만 반환

    Returns:
        {found: N, killed: M, errors: [...], connections: [...]}
    """
    try:
        zombies = await get_zombie_connections(redis_client, idle_threshold)
    except Exception as e:
        logger.error(f"CLIENT LIST 실패: {e}")
        return {"found": 0, "killed": 0, "errors": [str(e)], "connections": []}

    if dry_run:
        return {"found": len(zombies), "killed": 0, "errors": [], "connections": zombies}

    killed = 0
    errors = []
    for z in zombies:
        try:
            await redis_client.client_kill_filter(_id=z["id"])
            killed += 1
        except Exception as e:
            errors.append(f"id={z['id']}: {e}")

    return {"found": len(zombies), "killed": killed, "errors": errors, "connections": zombies}


def kill_zombie_connections_sync(
    host: str = "localhost",
    port: int = 6379,
    idle_threshold: int = 300,
    dry_run: bool = False,
) -> dict:
    """좀비 연결을 동기적으로 감지하고 kill한다 (CLI용).

    비동기 버전을 asyncio.run()으로 호출하여 판정 로직 중복을 방지한다.
    """
    async def _run() -> dict:
        client = aioredis.Redis(
            host=host,
            port=port,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        try:
            return await kill_zombie_connections(client, idle_threshold, dry_run)
        finally:
            await client.aclose()

    try:
        return asyncio.run(_run())
    except Exception as e:
        logger.error(f"동기 래퍼 실패: {e}")
        return {"found": 0, "killed": 0, "errors": [str(e)], "connections": []}
