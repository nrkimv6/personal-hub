"""LLM execution window policy.

Keeps the worker from starting new LLM subprocesses outside configured operator
windows while preserving queued requests as pending.
"""

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from app.shared.timezones import get_timezone


DEFAULT_TIMEZONE = "Asia/Seoul"
CONFIG_PATH = Path("data/llm_execution_windows.json")


@dataclass(frozen=True)
class ExecutionWindow:
    start: str
    end: str
    days: tuple[int, ...] | None = None

    def start_time(self) -> time:
        return _parse_hhmm(self.start)

    def end_time(self) -> time:
        return _parse_hhmm(self.end)

    def matches_start_day(self, day: int) -> bool:
        return self.days is None or day in self.days


@dataclass(frozen=True)
class ExecutionWindowDecision:
    allowed: bool
    reason: str | None = None
    next_allowed_at: datetime | None = None
    timezone: str = DEFAULT_TIMEZONE


def _parse_hhmm(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (AttributeError, ValueError):
        raise ValueError("time must be HH:MM")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("time must be HH:MM")
    return time(hour=hour, minute=minute)


def _normalize_window(raw: dict) -> ExecutionWindow:
    if not isinstance(raw, dict):
        raise ValueError("window must be an object")
    start = str(raw.get("start", "")).strip()
    end = str(raw.get("end", "")).strip()
    _parse_hhmm(start)
    _parse_hhmm(end)
    if start == end:
        raise ValueError("window start and end must differ")

    days_raw = raw.get("days")
    days = None
    if days_raw is not None:
        if not isinstance(days_raw, list) or not days_raw:
            raise ValueError("days must be a non-empty list")
        days_values = tuple(sorted({int(day) for day in days_raw}))
        if any(day < 0 or day > 6 for day in days_values):
            raise ValueError("days must be between 0 and 6")
        days = days_values

    return ExecutionWindow(start=start, end=end, days=days)


def _minute_of_day(value: time) -> int:
    return value.hour * 60 + value.minute


def _validate_no_overlaps(windows: list[ExecutionWindow], label: str) -> None:
    intervals: list[tuple[int, int]] = []
    for window in windows:
        days = window.days or tuple(range(7))
        start_minute = _minute_of_day(window.start_time())
        end_minute = _minute_of_day(window.end_time())
        for day in days:
            start = day * 1440 + start_minute
            end = day * 1440 + end_minute
            if end <= start:
                end += 1440
            intervals.append((start, end))
    intervals.sort()
    for previous, current in zip(intervals, intervals[1:]):
        if current[0] < previous[1]:
            raise ValueError(f"{label} windows overlap")


def _window_intervals(window: ExecutionWindow, now: datetime):
    start_t = window.start_time()
    end_t = window.end_time()
    base_date = now.date()
    for offset in range(-1, 2):
        start_dt = datetime.combine(base_date + timedelta(days=offset), start_t)
        if not window.matches_start_day(start_dt.weekday()):
            continue
        end_dt = datetime.combine(start_dt.date(), end_t)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        yield start_dt, end_dt


def _contains(window: ExecutionWindow, now: datetime) -> bool:
    return any(start <= now < end for start, end in _window_intervals(window, now))


def _is_allowed_at(now: datetime, allowed_windows: list[ExecutionWindow], quiet_windows: list[ExecutionWindow]) -> bool:
    if any(_contains(window, now) for window in quiet_windows):
        return False
    return not allowed_windows or any(_contains(window, now) for window in allowed_windows)


class LLMExecutionWindowService:
    """JSON-backed execution window configuration and decision helper."""

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or CONFIG_PATH

    def load_config(self) -> dict:
        if not self.config_path.exists():
            return {"timezone": DEFAULT_TIMEZONE, "allowed_windows": [], "quiet_windows": []}
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        return self.validate_config(raw)

    def save_config(self, payload: dict) -> dict:
        config = self.validate_config(payload)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return config

    @staticmethod
    def validate_config(payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        timezone = str(payload.get("timezone") or DEFAULT_TIMEZONE)
        try:
            get_timezone(timezone)
        except Exception as exc:
            raise ValueError(f"invalid timezone: {timezone}") from exc

        allowed = [_normalize_window(item) for item in payload.get("allowed_windows") or []]
        quiet = [_normalize_window(item) for item in payload.get("quiet_windows") or []]
        _validate_no_overlaps(allowed, "allowed")
        _validate_no_overlaps(quiet, "quiet")
        return {
            "timezone": timezone,
            "allowed_windows": [
                {"start": w.start, "end": w.end, **({"days": list(w.days)} if w.days else {})}
                for w in allowed
            ],
            "quiet_windows": [
                {"start": w.start, "end": w.end, **({"days": list(w.days)} if w.days else {})}
                for w in quiet
            ],
        }

    def decide(self, now: datetime | None = None) -> ExecutionWindowDecision:
        config = self.load_config()
        timezone = config["timezone"]
        tz = get_timezone(timezone)
        current = now or datetime.now(tz)
        if current.tzinfo is not None:
            current = current.astimezone(tz).replace(tzinfo=None)

        allowed_windows = [_normalize_window(item) for item in config["allowed_windows"]]
        quiet_windows = [_normalize_window(item) for item in config["quiet_windows"]]

        if not _is_allowed_at(current, allowed_windows, quiet_windows):
            return ExecutionWindowDecision(
                allowed=False,
                reason="paused_by_window",
                next_allowed_at=self.next_allowed_at(current, config),
                timezone=timezone,
            )

        return ExecutionWindowDecision(allowed=True, timezone=timezone)

    def next_allowed_at(self, now: datetime, config: dict | None = None) -> datetime | None:
        config = config or self.load_config()
        allowed_windows = [_normalize_window(item) for item in config["allowed_windows"]]
        quiet_windows = [_normalize_window(item) for item in config["quiet_windows"]]
        candidates: list[datetime] = []

        for window in allowed_windows:
            start_t = window.start_time()
            for offset in range(0, 8):
                candidate = datetime.combine(now.date() + timedelta(days=offset), start_t)
                if candidate < now:
                    continue
                if window.matches_start_day(candidate.weekday()):
                    candidates.append(candidate)

        for window in quiet_windows:
            for start, end in _window_intervals(window, now):
                if start <= now < end:
                    candidates.append(end)
                elif not allowed_windows and now < start:
                    candidates.append(now)

        valid = sorted(candidate for candidate in candidates if candidate >= now)
        for candidate in valid:
            if _is_allowed_at(candidate + timedelta(seconds=1), allowed_windows, quiet_windows):
                return candidate
        return None


def max_resume_at(*values: datetime | None) -> datetime | None:
    candidates = [value for value in values if value is not None]
    return max(candidates) if candidates else None
