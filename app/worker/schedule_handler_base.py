"""Schedule handler protocol and shared helpers.

Handlers are co-located under domain modules (``app/modules/*/schedulers``)
and return counts-only completion outcomes. The worker owns task creation,
complete/fail lifecycle, and run metadata patch persistence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional, Protocol

from app.models import TaskSchedule, TaskScheduleRun
from app.services.task_schedule_service import TaskScheduleService

if TYPE_CHECKING:
    from app.shared.browser.browser_manager import BrowserManager
    from sqlalchemy.orm import Session


@dataclass
class WorkerContext:
    worker_name: str
    browser_manager: Optional["BrowserManager"]
    db_factory: Callable[[], "Session"]
    execute_with_tab: Optional[Callable[..., Awaitable[Any]]] = None
    update_worker_state: Optional[Callable[[str, Optional[str], Optional[int]], None]] = None
    is_browser_closed_error: Optional[Callable[[Exception], bool]] = None
    reset_browser_manager: Optional[Callable[[], Awaitable[None]]] = None
    now: Optional[datetime] = None


@dataclass
class ClaimedRun:
    run: TaskScheduleRun
    task_name: str
    schedule_id: int = 0
    config_snapshot_patch: dict | None = None
    target_config_snapshot: dict | None = None


@dataclass
class HandlerRunOutcome:
    collected_count: int = 0
    saved_count: int = 0
    stop_reason: str | None = "completed"
    config_snapshot_patch: dict | None = None


class ScheduleHandler(Protocol):
    target_type: str

    def claim_run(
        self,
        db: "Session",
        schedule: TaskSchedule,
        svc: TaskScheduleService,
        ctx: WorkerContext,
    ) -> ClaimedRun | None:
        """Consume manual runs or due schedules and claim a run for execution."""

    async def execute(
        self,
        schedule: TaskSchedule,
        claimed: ClaimedRun,
        ctx: WorkerContext,
    ) -> HandlerRunOutcome:
        """Run the handler body and return counts-only completion metadata."""


def load_schedule_value(schedule: TaskSchedule) -> dict:
    """Parse ``schedule.schedule_value`` as a JSON object when available."""
    if not schedule.schedule_value:
        return {}
    try:
        value = json.loads(schedule.schedule_value)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def claim_pending_manual_run(
    db: "Session",
    schedule: TaskSchedule,
    svc: TaskScheduleService,
    ctx: WorkerContext,
    task_name_prefix: str,
) -> ClaimedRun | None:
    """Claim an existing pending manual run when one exists."""
    manual_run = svc.get_pending_manual_run(schedule.id)
    if not manual_run:
        return None

    manual_run.worker_id = ctx.worker_name
    db.commit()
    return ClaimedRun(
        run=manual_run,
        schedule_id=schedule.id,
        task_name=f"{task_name_prefix}_{schedule.id}_run_{manual_run.id}",
    )


def start_claimed_run(
    schedule: TaskSchedule,
    svc: TaskScheduleService,
    ctx: WorkerContext,
    task_name_prefix: str,
    config_snapshot: Optional[dict] = None,
    config_snapshot_patch: dict | None = None,
) -> ClaimedRun:
    """Create a new running schedule entry and wrap it as ``ClaimedRun``."""
    run = svc.start_run(
        schedule_id=schedule.id,
        worker_id=ctx.worker_name,
        config_snapshot=config_snapshot,
    )
    return ClaimedRun(
        run=run,
        schedule_id=schedule.id,
        task_name=f"{task_name_prefix}_{schedule.id}_run_{run.id}",
        config_snapshot_patch=config_snapshot_patch,
        target_config_snapshot=dict(config_snapshot or {}),
    )


def merge_config_snapshot(base: Optional[dict], patch: Optional[dict]) -> dict:
    """Shallow-merge run config snapshot metadata patches."""
    merged = dict(base or {})
    if patch:
        merged.update(patch)
    return merged
