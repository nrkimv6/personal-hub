from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from app.models import TaskSchedule
from app.models.plan_record import PlanRecord
from app.models.tracking_item import TrackingItem, TrackingItemPlanLink
from app.modules.dev_runner.services.worktree_hygiene_service import (
    REPORT_TYPE_WORKTREE_HYGIENE,
    WorktreeHygieneService,
    render_tracking_memo,
    render_worktree_hygiene_report,
    snapshot_to_statistics_json,
)
from app.modules.reports.models.generated_report import GeneratedReport
from app.services.task_schedule_service import TaskScheduleService
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleHandler,
    WorkerContext,
    start_claimed_run,
)
from app.worker.schedule_time_utils import should_run_cron

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class WorktreeHygieneScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_WORKTREE_HYGIENE

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
            logger.info("[%s] worktree_hygiene active run exists, skip", ctx.worker_name)
            return None
        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="worktree_hygiene",
            config_snapshot=schedule.get_target_config(),
        )

    async def execute(self, schedule: TaskSchedule, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        config = _normalize_config(schedule.get_target_config())
        service = WorktreeHygieneService(config["repo_root"])
        snapshot = service.collect(
            residue_retention_days=config["residue_retention_days"],
            auto_delete_residue=config["auto_delete_residue"] and not config["report_only"],
            stale_worktree_days=config["stale_worktree_days"],
        )
        content = render_worktree_hygiene_report(snapshot)
        now = datetime.now()

        with ctx.db_factory() as db:
            report = GeneratedReport(
                report_type=REPORT_TYPE_WORKTREE_HYGIENE,
                period_start=now,
                period_end=now,
                title=f"Worktree Hygiene Report {now:%Y-%m-%d}",
                content=content,
                summary=_build_summary(snapshot.statistics),
                statistics=snapshot_to_statistics_json(snapshot),
                schedule_run_id=claimed.run.id,
                format="markdown",
            )
            db.add(report)
            tracking_count = _upsert_tracking_candidates(db, snapshot.tracking_candidates)
            db.commit()

        config_patch = {
            "repo_root": str(config["repo_root"]),
            "report_type": REPORT_TYPE_WORKTREE_HYGIENE,
            "report_only": config["report_only"],
            "auto_delete_residue": config["auto_delete_residue"],
            "statistics": snapshot.statistics,
            "tracking_candidate_count": tracking_count,
        }
        return HandlerRunOutcome(
            collected_count=snapshot.statistics["registered_count"] + snapshot.statistics["residue_count"],
            saved_count=1,
            stop_reason="report_only" if config["report_only"] else "completed",
            config_snapshot_patch=config_patch,
        )


def _normalize_config(config: dict) -> dict:
    repo_root = Path(config.get("repo_root") or Path(__file__).parents[4]).resolve()
    return {
        "repo_root": repo_root,
        "residue_retention_days": int(config.get("residue_retention_days", 14)),
        "stale_worktree_days": int(config.get("stale_worktree_days", 14)),
        "auto_delete_residue": bool(config.get("auto_delete_residue", False)),
        "report_only": bool(config.get("report_only", True)),
    }


def _build_summary(statistics: dict) -> str:
    return (
        "registered={registered_count}, residue={residue_count}, "
        "stale_locked={stale_locked_review_count}, tracking={tracking_candidate_count}"
    ).format(**statistics)


def _normalize_path(value: str | None) -> str:
    return (value or "").replace("\\", "/").lower()


def _find_plan_record(db: "Session", plan_path: str) -> PlanRecord | None:
    target = _normalize_path(plan_path)
    if not target:
        return None
    records = db.query(PlanRecord).all()
    for record in records:
        if _normalize_path(record.file_path) == target:
            return record
    basename = Path(plan_path).name.lower()
    for record in records:
        if Path(record.file_path or "").name.lower() == basename:
            return record
    return None


def _upsert_tracking_candidates(db: "Session", candidates) -> int:
    updated = 0
    for candidate in candidates:
        key = {
            "risk_type": candidate.risk_type,
            "plan_path": candidate.plan_path,
            "worktree_path": candidate.worktree_path,
            "head": candidate.head,
        }
        title = f"archive 구현완료 plan의 live worktree reconcile: {candidate.plan_title or Path(candidate.plan_path).stem}"
        memo = render_tracking_memo(candidate)
        marker = json.dumps(key, ensure_ascii=False, sort_keys=True)
        existing = (
            db.query(TrackingItem)
            .filter(
                TrackingItem.completed_at.is_(None),
                TrackingItem.title == title,
                TrackingItem.description.like(f"%{marker}%"),
            )
            .first()
        )
        if existing:
            existing.description = f"{memo}\n\nsnapshot_key: {marker}\nlast_seen_at: {datetime.now().isoformat(timespec='seconds')}"
            existing.updated_at = datetime.now()
            item = existing
        else:
            item = TrackingItem(
                title=title,
                description=f"{memo}\n\nsnapshot_key: {marker}",
                start_at=datetime.now() + timedelta(days=1),
            )
            db.add(item)
            db.flush()
        plan_record = _find_plan_record(db, candidate.plan_path)
        if plan_record is not None:
            exists = (
                db.query(TrackingItemPlanLink)
                .filter_by(tracking_item_id=item.id, plan_record_id=plan_record.id)
                .first()
            )
            if exists is None:
                db.add(TrackingItemPlanLink(tracking_item_id=item.id, plan_record_id=plan_record.id))
        updated += 1
    return updated
