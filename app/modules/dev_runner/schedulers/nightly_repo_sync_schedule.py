from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from app.models import TaskSchedule
from app.models.tracking_item import TrackingItem
from app.modules.dev_runner.services.nightly_repo_sync_service import (
    REPORT_TYPE_NIGHTLY_REPO_SYNC,
    NightlyRepoSyncService,
    render_nightly_repo_sync_report,
    snapshot_to_statistics_json,
)
from app.modules.reports.models.generated_report import GeneratedReport
from app.services.task_schedule_service import TaskScheduleService
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleExecutionSpec,
    ScheduleHandler,
    WorkerContext,
    start_claimed_run,
)
from app.worker.schedule_time_utils import should_run_cron

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class NightlyRepoSyncScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC

    def claim_run(
        self,
        db: "Session",
        schedule: TaskSchedule,
        svc: TaskScheduleService,
        ctx: WorkerContext,
    ) -> ClaimedRun | None:
        last_run = svc.get_latest_run(schedule.id)
        last_run_at = last_run.started_at if last_run else None
        if not should_run_cron(schedule, last_run_at):
            return None
        if svc.has_active_run(schedule.id):
            logger.info("[%s] nightly_repo_sync active run exists, skip", ctx.worker_name)
            return None
        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="nightly_repo_sync",
            config_snapshot=schedule.get_target_config(),
        )

    async def execute(self, spec: ScheduleExecutionSpec, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        config = _normalize_config(spec.target_config)
        service = NightlyRepoSyncService(config["repo_root"])
        snapshot = service.run(allow_mutation=config["allow_mutation"])
        content = render_nightly_repo_sync_report(snapshot)
        now = datetime.now()

        with ctx.db_factory() as db:
            report = GeneratedReport(
                report_type=REPORT_TYPE_NIGHTLY_REPO_SYNC,
                period_start=now,
                period_end=now,
                title=f"Nightly Repo Sync Report {now:%Y-%m-%d}",
                content=content,
                summary=_build_summary(snapshot),
                statistics=snapshot_to_statistics_json(snapshot),
                schedule_run_id=claimed.run_id,
                format="markdown",
            )
            db.add(report)
            tracking_count = _upsert_tracking_decision(db, snapshot.tracking)
            db.commit()

        return HandlerRunOutcome(
            collected_count=len(snapshot.actions),
            saved_count=1,
            stop_reason=snapshot.tracking.status if snapshot.tracking else "completed",
            config_snapshot_patch={
                "repo_root": str(config["repo_root"]),
                "allow_mutation": config["allow_mutation"],
                "report_type": REPORT_TYPE_NIGHTLY_REPO_SYNC,
                "tracking_count": tracking_count,
            },
        )


def _normalize_config(config: dict) -> dict:
    return {
        "repo_root": Path(config.get("repo_root") or Path(__file__).parents[4]).resolve(),
        "allow_mutation": bool(config.get("allow_mutation", True)),
    }


def _build_summary(snapshot) -> str:
    block = snapshot.tracking.block_reason if snapshot.tracking else None
    return (
        f"root_ahead={snapshot.root.ahead}, root_behind={snapshot.root.behind}, "
        f"root_dirty={snapshot.root.dirty}, block={block or '-'}"
    )


def _upsert_tracking_decision(db: "Session", decision) -> int:
    if decision is None or decision.status == "completed":
        return 0
    marker = f"nightly_repo_sync:block:{decision.block_reason or 'unknown'}"
    existing = (
        db.query(TrackingItem)
        .filter(
            TrackingItem.completed_at.is_(None),
            TrackingItem.title == decision.title,
            TrackingItem.description.like(f"%{marker}%"),
        )
        .first()
    )
    description = f"{decision.description}\n\nsnapshot_key: {marker}\nlast_seen_at: {datetime.now().isoformat(timespec='seconds')}"
    if existing:
        existing.description = description
        existing.updated_at = datetime.now()
    else:
        db.add(
            TrackingItem(
                title=decision.title,
                description=description,
                start_at=datetime.now() + timedelta(days=1),
            )
        )
    return 1
