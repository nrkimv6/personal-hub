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
from app.modules.dev_runner.services.visibility import is_visible_runner_evidence
from app.modules.dev_runner.services.runner_display_state import build_display_state
from app.modules.dev_runner.services.runner_read_model import build_runner_read_model

# 새 필드 추가 시 _status_values() defaults에 키를 추가하면 자동 동기화됨
STATUS_FIELDS: tuple[str, ...] = (
    "status",
    "pid",
    "current_cycle",
    "start_time",
    "plan_file",
    "engine",
    "log_file_path",
    "stream_log_path",
    "worktree_path",
    "branch",
    "trigger",
    "test_source",
    "merge_status",
    "merge_reason",
    "merge_message",
    "exit_reason",
    "stop_stage",
    "error",
    "execution_count",
    "worktree_exists",
    "branch_exists",
    "branch_merged_to_main",
    "metadata_checked_at",
    "gate_evidence_summary",
)


def _decode_text(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _coerce_metadata_state(value):
    if isinstance(value, bool):
        return value
    text = _decode_text(value)
    if text is None:
        return "unknown"
    normalized = str(text).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return "unknown"


def _coerce_metadata_checked_at(value) -> str:
    text = _decode_text(value)
    if text is None or str(text).strip() == "":
        return "unknown"
    return str(text)


def _coerce_json_dict(value) -> dict | None:
    text = _decode_text(value)
    if text is None:
        return None
    if isinstance(text, dict):
        return text
    try:
        import json

        parsed = json.loads(str(text))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def build_status_payload(sync_redis, runner_id: str) -> Optional[dict]:
    """특정 runner의 현재 상태를 Redis에서 읽어 dict로 반환"""
    try:
        values = sync_redis.mget([f"{RUNNER_KEY_PREFIX}:{runner_id}:{f}" for f in STATUS_FIELDS])
        data = dict(zip(STATUS_FIELDS, values))
        data["runner_id"] = runner_id
        data["visible"] = is_visible_runner_evidence(
            runner_id=runner_id,
            trigger=data.get("trigger"),
            plan_file=data.get("plan_file"),
            worktree_path=data.get("worktree_path"),
            branch=data.get("branch"),
            status=data.get("status"),
            test_source=data.get("test_source"),
            log_file=data.get("stream_log_path") or data.get("log_file_path"),
        )
        data["worktree_exists"] = _coerce_metadata_state(data.get("worktree_exists"))
        data["branch_exists"] = _coerce_metadata_state(data.get("branch_exists"))
        data["branch_merged_to_main"] = _coerce_metadata_state(data.get("branch_merged_to_main"))
        data["metadata_checked_at"] = _coerce_metadata_checked_at(data.get("metadata_checked_at"))
        data["gate_evidence_summary"] = _coerce_json_dict(data.get("gate_evidence_summary"))
        read_model = build_runner_read_model(
            runner_id=runner_id,
            running=data.get("status") == "running",
            merge_status=_decode_text(data.get("merge_status")),
            exit_reason=_decode_text(data.get("exit_reason")),
            branch=_decode_text(data.get("branch")),
            worktree_path=_decode_text(data.get("worktree_path")),
            redis_branch_exists=data["branch_exists"],
            redis_worktree_exists=data["worktree_exists"],
        )
        display = build_display_state(read_model)
        data["branch_exists"] = read_model.branch_exists
        data["worktree_exists"] = read_model.worktree_exists
        data["display_state"] = display.state
        data["display_label"] = display.label
        data["display_severity"] = display.severity
        data["display_secondary"] = display.secondary
        data["hide_stale_branch_badge"] = display.hide_stale_branch_badge
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
