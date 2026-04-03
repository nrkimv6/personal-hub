"""카카오 모니터 워커 런타임 상태 공유 저장소.

worker(main)와 status API(worker_routes)가 같은 프로세스 내에서
등록/루프/오류 상태를 공유하기 위한 경량 모듈입니다.
"""
from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any

_LOCK = Lock()

_STATE: dict[str, Any] = {
    "worker_registered": False,
    "registration_stage": None,
    "registration_error": None,
    "last_loop_at": None,
    "last_error": None,
    "active_config_count": 0,
    "active_keyword_count": 0,
    "loop_interval_sec": None,
    "idle_reason": "worker not initialized",
    "capture_failures": 0,
    "ocr_failures": 0,
    "keyword_miss_count": 0,
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mark_registration(
    *,
    registered: bool,
    stage: str,
    error: str | None = None,
) -> None:
    """워커 등록 상태를 기록한다."""
    with _LOCK:
        _STATE["worker_registered"] = registered
        _STATE["registration_stage"] = stage
        _STATE["registration_error"] = error
        if error:
            _STATE["last_error"] = error
        if registered:
            _STATE["idle_reason"] = None


def mark_loop(
    *,
    active_config_count: int,
    active_keyword_count: int,
    loop_interval_sec: float,
    idle_reason: str | None = None,
) -> None:
    """루프 실행 상태를 갱신한다."""
    with _LOCK:
        _STATE["last_loop_at"] = _now_iso()
        _STATE["active_config_count"] = active_config_count
        _STATE["active_keyword_count"] = active_keyword_count
        _STATE["loop_interval_sec"] = round(float(loop_interval_sec), 2)
        _STATE["idle_reason"] = idle_reason


def mark_error(message: str) -> None:
    """최근 오류를 기록한다."""
    with _LOCK:
        _STATE["last_error"] = message
        _STATE["last_loop_at"] = _now_iso()


def increment_counter(counter_key: str) -> None:
    """단순 카운터 필드를 1 증가시킨다."""
    with _LOCK:
        value = _STATE.get(counter_key, 0)
        if not isinstance(value, int):
            value = 0
        _STATE[counter_key] = value + 1


def get_runtime_status() -> dict[str, Any]:
    """현재 런타임 상태 스냅샷을 반환한다."""
    with _LOCK:
        return dict(_STATE)

