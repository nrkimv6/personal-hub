"""Shared due-check helpers for schedule handlers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.models import TaskSchedule
from app.modules.instagram.models.schemas import TimeWindow
from app.modules.instagram.services.scheduler import InstagramScheduler

logger = logging.getLogger(__name__)


def parse_time_windows(raw_windows: list) -> Optional[list[TimeWindow]]:
    """Parse supported time-window formats into ``TimeWindow`` models."""
    if not raw_windows:
        return None

    result: list[TimeWindow] = []
    for time_window in raw_windows:
        if isinstance(time_window, list):
            if len(time_window) != 2:
                logger.warning("Invalid time window list format: %s", time_window)
                continue
            time_window = {"start": time_window[0], "end": time_window[1]}

        if "start_hour" in time_window and "start" not in time_window:
            time_window = {
                "start": f"{time_window['start_hour']:02d}:00",
                "end": f"{time_window['end_hour']:02d}:00",
            }
        result.append(TimeWindow(**time_window))

    return result or None


def build_time_window_scheduler(config: dict, default_daily_runs: int = 1) -> InstagramScheduler:
    """Build the existing InstagramScheduler-based due checker."""
    return InstagramScheduler(
        daily_runs=config.get("daily_runs", default_daily_runs),
        time_windows=parse_time_windows(config.get("time_windows", [])),
    )


def should_run_simple_interval(last_run_at: Optional[datetime], min_interval_hours: int) -> bool:
    """Return ``True`` when a simple interval schedule is due."""
    if last_run_at is None:
        return True
    hours_since = (datetime.now() - last_run_at).total_seconds() / 3600
    return hours_since >= min_interval_hours


def should_run_cron(schedule: TaskSchedule, last_run_at: Optional[datetime]) -> bool:
    """Return ``True`` when a cron schedule is due."""
    from app.services.pytest_runner_service import should_run_cron_now

    return should_run_cron_now(schedule.schedule_value or "", last_run_at)
