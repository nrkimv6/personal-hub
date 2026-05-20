"""Shared schedule payload contract helpers."""

from __future__ import annotations

import json
from datetime import date as date_type, timedelta
from typing import Any

from app.modules.instagram.models.schemas import TimeWindow


SCHEDULE_HEALTH_OK = "ok"
SCHEDULE_HEALTH_WARNING = "warning"
SCHEDULE_HEALTH_ERROR = "error"


def _decode_schedule_value(schedule_value: Any) -> tuple[dict[str, Any], str | None]:
    if schedule_value is None:
        return {}, None
    if isinstance(schedule_value, str):
        try:
            parsed = json.loads(schedule_value)
        except json.JSONDecodeError:
            return {}, "invalid_schedule_value_json"
        return (parsed, None) if isinstance(parsed, dict) else ({}, "invalid_schedule_value_shape")
    return (schedule_value, None) if isinstance(schedule_value, dict) else ({}, "invalid_schedule_value_shape")


def coerce_schedule_value(schedule_value: Any) -> dict[str, Any]:
    """Return a dict schedule payload, or an empty dict for invalid values."""
    value, _error = _decode_schedule_value(schedule_value)
    return value


def _coerce_schedule_value(schedule_value: Any) -> dict[str, Any]:
    return coerce_schedule_value(schedule_value)


def has_exact_time_window(schedule_value: Any) -> bool:
    """Return True when a payload contains legacy ``start == end`` windows."""
    value = _coerce_schedule_value(schedule_value)
    windows = value.get("time_windows")
    if not isinstance(windows, list):
        return False

    for window in windows:
        if not isinstance(window, dict):
            continue
        start = window.get("start")
        end = window.get("end")
        if isinstance(start, str) and isinstance(end, str) and start == end:
            return True
    return False


def validate_no_exact_time_windows(schedule_value: Any) -> None:
    """Reject new writes of legacy exact-slot time windows."""
    if has_exact_time_window(schedule_value):
        raise ValueError("time_windows의 start와 end는 같을 수 없습니다. 시작/종료 범위로 수정하세요.")


def build_time_window_candidate_summary(
    schedule_value: Any,
    *,
    days: int = 1,
    start_date: date_type | None = None,
) -> dict[str, Any]:
    """Summarize random time-window candidate health for a schedule payload."""
    from app.modules.instagram.services.scheduler import InstagramScheduler

    if start_date is None:
        start_date = date_type.today()
    days = max(1, days)

    value, decode_error = _decode_schedule_value(schedule_value)
    if decode_error:
        return {
            "health": SCHEDULE_HEALTH_ERROR,
            "reason": decode_error,
            "candidate_count": 0,
            "daily_runs": 0,
            "time_window_count": 0,
            "has_exact_time_window": False,
        }

    raw_windows = value.get("time_windows")
    daily_runs = value.get("daily_runs", 0)
    try:
        daily_runs = int(daily_runs)
    except (TypeError, ValueError):
        daily_runs = 0

    if not isinstance(raw_windows, list):
        raw_windows = []

    has_exact = has_exact_time_window(value)
    try:
        time_windows = [
            TimeWindow(**window)
            for window in raw_windows
            if isinstance(window, dict)
        ]
    except Exception:
        return {
            "health": SCHEDULE_HEALTH_ERROR,
            "reason": "invalid_time_windows",
            "candidate_count": 0,
            "daily_runs": daily_runs,
            "time_window_count": len(raw_windows),
            "has_exact_time_window": has_exact,
        }

    scheduler = InstagramScheduler(daily_runs=daily_runs, time_windows=time_windows)
    candidate_count = sum(
        len(scheduler.generate_daily_schedule(start_date + timedelta(days=offset)))
        for offset in range(days)
    )

    if daily_runs > 0 and time_windows and candidate_count == 0:
        health = SCHEDULE_HEALTH_ERROR
        reason = "exact_time_window_zero_candidates" if has_exact else "zero_candidates"
    elif has_exact:
        health = SCHEDULE_HEALTH_WARNING
        reason = "requires_time_window_repair"
    else:
        health = SCHEDULE_HEALTH_OK
        reason = None

    return {
        "health": health,
        "reason": reason,
        "candidate_count": candidate_count,
        "daily_runs": daily_runs,
        "time_window_count": len(time_windows),
        "has_exact_time_window": has_exact,
    }
