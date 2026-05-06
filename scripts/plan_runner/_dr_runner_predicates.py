"""_dr_runner_predicates.py — runner 상태 판별 서술자 (scripts 환경 독립)

이 모듈은 app.modules를 import하지 않으며, scripts 환경에서 단독 실행 가능하다.
"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject


import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Iterable, Optional

import psutil
import redis

from _dr_constants import RUNNER_KEY_PREFIX, PLAN_FILE_ALL, _LEGACY_ALL
from _dr_plan_paths import classify_plan_stage, read_plan_status
from _dr_runtime_utils import _normalize_exit_reason

logger = logging.getLogger(__name__)


def _hash_process_cmdline(cmdline: Iterable[object] | None) -> str:
    """Return a stable hash for a process command line."""
    normalized = [str(part) for part in (cmdline or [])]
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_process_identity(pid: int, fallback_cmdline: Iterable[object] | None = None) -> dict | None:
    """Return OS process identity fields used to defend against PID reuse."""
    try:
        proc = psutil.Process(pid)
        create_time = proc.create_time()
        try:
            cmdline = proc.cmdline()
        except (psutil.AccessDenied, psutil.ZombieProcess) as exc:
            if fallback_cmdline is None:
                logger.debug("[process-identity] cmdline unavailable for pid=%s: %s", pid, exc)
                return None
            cmdline = fallback_cmdline
        return {
            "pid_create_time": create_time,
            "process_cmdline_hash": _hash_process_cmdline(cmdline),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
        logger.debug("[process-identity] unavailable for pid=%s: %s", pid, exc)
        return None
    except Exception as exc:
        logger.debug("[process-identity] failed for pid=%s: %s", pid, exc)
        return None


def _runner_identity_matches(
    redis_client: redis.Redis,
    runner_id: str,
    pid: int,
    *,
    startup_grace_seconds: int = 600,
) -> tuple[bool, str]:
    """Check whether the alive PID is still the runner process we launched."""
    try:
        expected_create_time = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid_create_time")
        expected_cmdline_hash = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:process_cmdline_hash")
    except Exception as exc:
        logger.warning("[process-identity] redis lookup failed runner=%s pid=%s: %s", runner_id, pid, exc)
        return False, "identity_lookup_failed"

    if not expected_create_time or not expected_cmdline_hash:
        is_recent_legacy, start_elapsed = _is_recent_runner_without_hb(
            redis_client,
            runner_id,
            startup_grace_seconds=startup_grace_seconds,
        )
        if is_recent_legacy:
            return True, "legacy_grace"
        elapsed_text = "unknown" if start_elapsed is None else f"{start_elapsed:.0f}s"
        logger.warning(
            "[process-identity] missing metadata runner=%s pid=%s start_elapsed=%s",
            runner_id,
            pid,
            elapsed_text,
        )
        return False, "identity_missing"

    actual = _get_process_identity(pid)
    if actual is None:
        return False, "process_unavailable"

    try:
        expected_create = float(expected_create_time)
        actual_create = float(actual["pid_create_time"])
    except (TypeError, ValueError):
        return False, "pid_create_time_invalid"

    if abs(actual_create - expected_create) > 0.01:
        return False, "pid_create_time_mismatch"
    if str(actual["process_cmdline_hash"]) != str(expected_cmdline_hash):
        return False, "process_cmdline_mismatch"
    return True, "identity_match"


def _is_user_visible_trigger(trigger: Optional[str], runner_id: str = "") -> bool:
    """trigger=user/user:all 이고 TC 접두사가 없는 경우 True.

    visibility.py is_visible_runner와 동일 계약 (scripts 환경 독립 버전).
    TC 기준: "tc-pytest-" 접두사 (실제 테스트 runner_id 패턴 기반)
    """
    if runner_id.startswith("tc-pytest-"):
        return False
    return trigger in ("user", "user:all")


def _is_pre_review_stopped_runner(runner_id: str, redis_client: redis.Redis) -> bool:
    """runner가 검토완료 이전(pre_review) 중지 상태인지 판별."""
    try:
        stop_stage = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage")
        if stop_stage == "pre_review":
            return True
        if stop_stage == "post_review":
            return False
    except Exception:
        pass

    try:
        exit_reason = _normalize_exit_reason(
            redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason")
        )
    except Exception:
        exit_reason = ""
    if exit_reason != "stopped":
        return False

    try:
        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        if not plan_file or plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
            return False
        stage = classify_plan_stage(read_plan_status(plan_file))
        if stage in ("pre_review", "post_review"):
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage", stage)
            except Exception:
                pass
        return stage == "pre_review"
    except Exception:
        return False


def _is_pid_alive(pid: int) -> bool:
    """PID가 실제로 살아있는지 OS 레벨 확인 (Windows)"""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        STILL_ACTIVE = 259
        exit_code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        return exit_code.value == STILL_ACTIVE
    except Exception:
        return False


def _parse_start_elapsed_seconds(start_time_raw, now_ts: Optional[float] = None) -> Optional[float]:
    """start_time 값(epoch/isoformat)을 경과 초로 변환. 변환 불가 시 None."""
    if start_time_raw in (None, ""):
        return None

    raw = str(start_time_raw).strip()
    if not raw:
        return None

    current_ts = time.time() if now_ts is None else now_ts

    # 1) epoch seconds/milliseconds 처리
    try:
        start_ts = float(raw)
        if start_ts > 1e12:  # milliseconds
            start_ts = start_ts / 1000.0
        return max(0.0, current_ts - start_ts)
    except Exception:
        pass

    # 2) ISO8601 문자열 처리 (naive datetime 포함)
    try:
        start_dt = datetime.fromisoformat(raw)
        return max(0.0, current_ts - start_dt.timestamp())
    except Exception:
        return None


def _is_recent_runner_without_hb(
    redis_client: redis.Redis,
    runner_id: str,
    startup_grace_seconds: int = 600,
) -> tuple[bool, Optional[float]]:
    """subprocess_heartbeat 미존재 시, start_time 기준으로 최근 실행 runner인지 판정."""
    try:
        start_time_raw = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time")
    except Exception:
        return False, None

    start_elapsed = _parse_start_elapsed_seconds(start_time_raw)
    if start_elapsed is None:
        return False, None
    return start_elapsed < startup_grace_seconds, start_elapsed
