from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import and_

from app.models import TaskSchedule
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.services.plan_analyze_handler import build_plan_analyze_prompt
from app.modules.dev_runner.services.plan_record_service import _is_temp_pytest_path
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
DEFAULT_MAX_BACKFILL_PER_RUN = 25


class PlanArchiveScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE

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

        logger.info("[%s] plan_archive_analyze 실행 시간 도래: schedule_id=%s", ctx.worker_name, schedule.id)
        if svc.has_active_run(schedule.id):
            logger.info("[%s] 이미 활성 실행 존재, 스킵", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="plan_archive_analyze",
            config_snapshot={},
        )

    async def execute(self, schedule: TaskSchedule, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        loop = asyncio.get_event_loop()
        target_config = schedule.get_target_config() if schedule.target_config else {}
        stats = await loop.run_in_executor(
            None,
            self._enqueue_unprocessed_plans,
            ctx.db_factory,
            target_config,
        )
        count = stats["queued"]
        return HandlerRunOutcome(
            collected_count=count,
            saved_count=count,
            stop_reason="completed",
            config_snapshot_patch=stats,
        )

    @staticmethod
    def _get_max_backfill_per_run(target_config: dict | None) -> int:
        raw_value = (target_config or {}).get("max_backfill_per_run", DEFAULT_MAX_BACKFILL_PER_RUN)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return DEFAULT_MAX_BACKFILL_PER_RUN
        return value if value > 0 else DEFAULT_MAX_BACKFILL_PER_RUN

    @classmethod
    def _enqueue_unprocessed_plans(cls, db_factory, target_config: dict | None = None) -> dict:
        db = db_factory()
        try:
            return cls._enqueue_unprocessed_plans_in_session(db, target_config=target_config)
        finally:
            db.close()

    @classmethod
    def _enqueue_unprocessed_plans_in_session(cls, db: "Session", target_config: dict | None = None) -> dict:
        target_config = target_config or {}
        include_temp_records = target_config.get("include_temp_records") is True
        max_backfill_per_run = cls._get_max_backfill_per_run(target_config)
        stats = {
            "queued": 0,
            "skipped_temp": 0,
            "skipped_empty": 0,
            "skipped_active_request": 0,
            "remaining_real_unprocessed": 0,
        }
        try:
            base_query = db.query(PlanRecord).filter(
                and_(
                    PlanRecord.llm_processed_at.is_(None),
                    PlanRecord.archived_at.isnot(None),
                )
            )
            all_unprocessed = base_query.order_by(PlanRecord.archived_at.asc()).all()
            if not all_unprocessed:
                return stats

            real_candidates = [
                record
                for record in all_unprocessed
                if include_temp_records or not _is_temp_pytest_path(record.file_path)
            ]
            stats["skipped_temp"] = 0 if include_temp_records else len(all_unprocessed) - len(real_candidates)
            stats["remaining_real_unprocessed"] = len(real_candidates)
            records = real_candidates[:max_backfill_per_run]
            if not records:
                return stats

            existing_active = {
                row[0]
                for row in db.query(LLMRequest.caller_id)
                .filter(
                    and_(
                        LLMRequest.caller_type == "plan_archive_analyze",
                        LLMRequest.status.in_(["pending", "processing"]),
                        LLMRequest.deleted_at.is_(None),
                    )
                )
                .all()
            }

            inserted = 0
            llm_service = LLMService(db)
            provider, model = llm_service.resolve_provider_model(
                caller_type="plan_archive_analyze",
                provider=None,
                model=None,
            )

            for record in records:
                if record.filename_hash in existing_active:
                    stats["skipped_active_request"] += 1
                    continue

                file_content = record.raw_content or ""
                if not file_content.strip():
                    try:
                        file_path = Path(record.file_path)
                        if file_path.exists():
                            file_content = file_path.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        pass

                if not file_content.strip():
                    stats["skipped_empty"] += 1
                    logger.warning("[scheduler] plan 내용 없음 — LLMRequest 생성 스킵: %s", record.file_path)
                    continue

                prompt = build_plan_analyze_prompt(
                    file_content=file_content,
                    filename=Path(record.file_path).name,
                )
                llm_request = LLMRequest(
                    caller_type="plan_archive_analyze",
                    caller_id=record.filename_hash,
                    prompt=prompt,
                    queue_name="utility",
                    requested_by="scheduler",
                    provider=provider,
                    model=model,
                )
                db.add(llm_request)
                inserted += 1

            if inserted > 0:
                db.commit()
            stats["queued"] = inserted
            stats["remaining_real_unprocessed"] = max(
                stats["remaining_real_unprocessed"] - inserted - stats["skipped_active_request"],
                0,
            )
            return stats
        except Exception:
            db.rollback()
            raise
