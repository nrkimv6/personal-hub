"""event_payload — Redis 읽기 계층 (payload 빌드 + 상태 안정화)

A+D 도메인: build_status_payload, build_all_runners_status, build_tracking_payload,
            read_runner_error, stabilize_commit_failed_status_payload
상태 없음. sync_redis를 인자로 받아 fakeredis 직접 주입 가능.
"""
import asyncio
from typing import Optional

from app.modules.dev_runner.services.event_routing import (
    RUNNER_KEY_PREFIX,
    ACTIVE_RUNNERS_KEY,
    RECENT_RUNNERS_KEY,
    REDIS_STATE_KEY,
    MAX_RECENT_IN_SSE,
)
from app.modules.dev_runner.services.visibility import is_visible_runner


def build_status_payload(sync_redis, runner_id: str) -> Optional[dict]:
    """특정 runner의 현재 상태를 Redis에서 읽어 dict로 반환"""
    try:
        fields = [
            "status",
            "pid",
            "current_cycle",
            "start_time",
            "plan_file",
            "engine",
            "worktree_path",
            "branch",
            "trigger",
            "merge_status",
            "merge_reason",
            "merge_message",
            "exit_reason",
            "stop_stage",
            "error",
            "execution_count",
        ]
        values = sync_redis.mget([f"{RUNNER_KEY_PREFIX}:{runner_id}:{f}" for f in fields])
        data = dict(zip(fields, values))
        data["runner_id"] = runner_id
        data["visible"] = is_visible_runner(data.get("trigger"), runner_id)
        # plan_file이 None(Redis 키 미설정)이면 None 반환 — sentinel fallback 제거
        if not data.get("plan_file"):
            data["plan_file"] = None
        return data
    except Exception:
        return None


def build_all_runners_status(sync_redis) -> list:
    """모든 active + RECENT visible runner 상태를 묶어서 반환"""
    try:
        active_ids: set = sync_redis.smembers(ACTIVE_RUNNERS_KEY) or set()
        # 전체 recent runner를 가져온 후 visible 필터링
        recent_ids: list = sync_redis.zrange(RECENT_RUNNERS_KEY, 0, -1) or []
        all_ids = active_ids | set(recent_ids)
        result = []
        for rid in all_ids:
            payload = build_status_payload(sync_redis, rid)
            if payload:
                if not payload.get("visible", False):
                    continue
                result.append(payload)
                if len(result) >= MAX_RECENT_IN_SSE:
                    break
        return result
    except Exception:
        return []


def build_tracking_payload(sync_redis) -> Optional[dict]:
    """현재 추적 중인 태스크 정보를 Redis에서 읽어 dict로 반환"""
    try:
        keys = [
            f"{REDIS_STATE_KEY}:current_task_text",
            f"{REDIS_STATE_KEY}:current_task_confidence",
            f"{REDIS_STATE_KEY}:current_task_line_num",
            f"{REDIS_STATE_KEY}:current_task_plan_file",
        ]
        text, confidence, line_num, plan_file = sync_redis.mget(keys)
        if not text:
            return None
        return {
            "text": text,
            "confidence": confidence,
            "line_num": int(line_num) if line_num else None,
            "plan_file": plan_file,
        }
    except Exception:
        return None


def read_runner_error(sync_redis, runner_id: str) -> Optional[str]:
    """runner error 값을 Redis에서 읽는다."""
    try:
        return sync_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:error")
    except Exception:
        return None


async def read_runner_error_with_retry(
    sync_redis,
    runner_id: str,
    retries: int = 1,
    delay: float = 0.05,
) -> Optional[str]:
    """commit_failed 같은 순서 경쟁을 흡수하기 위해 error를 한 번 더 재조회한다."""
    error = read_runner_error(sync_redis, runner_id)
    if error:
        return error
    for _ in range(retries):
        await asyncio.sleep(delay)
        error = read_runner_error(sync_redis, runner_id)
        if error:
            return error
    return None


async def stabilize_commit_failed_status_payload(
    sync_redis, runner_id: str, payload: dict
) -> dict:
    """exit_reason=commit_failed일 때 error 키 반영이 늦어도 한 번 더 흡수한다."""
    if payload.get("exit_reason") != "commit_failed" or payload.get("error"):
        return payload

    await asyncio.sleep(0.05)
    refreshed = build_status_payload(sync_redis, runner_id)
    if refreshed and refreshed.get("error"):
        return refreshed
    return payload
