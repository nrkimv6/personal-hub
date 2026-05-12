"""Shared schedule payload contract helpers."""

from __future__ import annotations

import json
from typing import Any


def _coerce_schedule_value(schedule_value: Any) -> dict[str, Any]:
    if schedule_value is None:
        return {}
    if isinstance(schedule_value, str):
        try:
            parsed = json.loads(schedule_value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return schedule_value if isinstance(schedule_value, dict) else {}


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
