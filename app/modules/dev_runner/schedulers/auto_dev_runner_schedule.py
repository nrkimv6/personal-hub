"""야간 자동 plan 진행 스케줄러 (auto_dev_runner)

매일 02:00 실행. plan 디렉토리에서 전일/전전일 생성 + auto_run:true plan을 골라
dev-runner로 자동 진행하고 결과를 logs/daily-reports/auto-runs-YYYY-MM-DD.json에 누적.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.config import PROJECT_ROOT
from app.models import TaskSchedule
from app.modules.dev_runner.schemas import RunRequest
from app.modules.dev_runner.services.auto_run_validator import validate_scope
from app.modules.dev_runner.services.plan_frontmatter import (
    AUTO_RUN_SCOPES,
    read_auto_run_meta,
    write_frontmatter_field,
)
from app.services.task_schedule_service import TaskScheduleService
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleHandler,
    WorkerContext,
    claim_pending_manual_run,
    start_claimed_run,
)
from app.worker.schedule_time_utils import should_run_cron

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_PLANS_DIR = PROJECT_ROOT / ".worktrees" / "plans" / "docs" / "plan"
_DAILY_REPORTS_DIR = PROJECT_ROOT / "logs" / "daily-reports"

# plan 파일명에서 날짜 추출
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")

# 자동 실행 대상 상태 (이미 구현 중이면 제외)
_AUTO_ELIGIBLE_STATUSES = {"초안", "검토완료"}


def _get_plan_date(path: Path) -> date | None:
    m = _DATE_RE.match(path.name)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _get_plan_status(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")[:1500]
    except OSError:
        return None
    m = re.search(r"^>\s*상태:\s*(.+)", content, re.MULTILINE)
    return m.group(1).strip() if m else None


def _collect_eligible_plans(today: date) -> list[Path]:
    """전일/전전일 생성 + auto_run:true + 미실행 + 허용 상태 plan 목록."""
    yesterday = today - timedelta(days=1)
    day_before = today - timedelta(days=2)
    target_dates = {yesterday, day_before}

    if not _PLANS_DIR.exists():
        return []

    eligible = []
    for plan_path in sorted(_PLANS_DIR.glob("*.md")):
        plan_date = _get_plan_date(plan_path)
        if plan_date not in target_dates:
            continue

        meta = read_auto_run_meta(plan_path)
        auto_run = (meta.get("auto_run") or "").lower()
        if auto_run != "true":
            continue

        auto_run_status = meta.get("auto_run_status")
        if auto_run_status:
            logger.debug("[auto_dev_runner] skip (already run): %s", plan_path.name)
            continue

        status = _get_plan_status(plan_path)
        if status not in _AUTO_ELIGIBLE_STATUSES:
            logger.debug("[auto_dev_runner] skip (status=%s): %s", status, plan_path.name)
            continue

        eligible.append(plan_path)

    return eligible


def _append_run_result(today: date, run_result: dict) -> None:
    _DAILY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _DAILY_REPORTS_DIR / f"auto-runs-{today}.json"
    existing: dict = {}
    if report_path.exists():
        try:
            existing = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    runs: list = existing.get("runs", [])
    runs.append(run_result)
    existing["date"] = str(today)
    existing["generated_at"] = datetime.now().isoformat()
    existing["runs"] = runs
    report_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


async def _run_single_plan(plan_path: Path, today: date) -> dict:
    """단일 plan 실행 후 결과 dict 반환."""
    from app.modules.dev_runner.services.executor_service import executor_service

    plan_id = plan_path.stem
    meta = read_auto_run_meta(plan_path)
    scope = meta.get("auto_run_scope") or "safe-fix"

    result: dict = {
        "plan_id": plan_id,
        "scope": scope,
        "status": "failed",
        "merged": False,
        "changed_files": [],
        "tc_results": {},
        "suspicions": [],
        "log_path": "",
        "started_at": datetime.now().isoformat(),
        "ended_at": "",
    }

    # scope 검증
    suspicions = validate_scope(plan_path, scope)
    if suspicions:
        result["suspicions"] = suspicions
        result["status"] = "skipped"
        logger.warning("[auto_dev_runner] scope mismatch, abort: %s => %s", plan_id, suspicions)
        write_frontmatter_field(plan_path, "auto_run_status", "skipped")
        write_frontmatter_field(plan_path, "auto_run_at", datetime.now().isoformat())
        result["ended_at"] = datetime.now().isoformat()
        return result

    try:
        request = RunRequest(
            plan_file=str(plan_path),
            worktree=True,
            trigger="scheduler:auto_dev_runner",
        )
        run_status = await executor_service.start_dev_runner(request)
        result["status"] = "completed"
        logger.info("[auto_dev_runner] started runner_id=%s plan=%s", run_status.runner_id, plan_id)
        write_frontmatter_field(plan_path, "auto_run_status", "completed")
    except Exception as exc:
        result["status"] = "failed"
        result["suspicions"].append(f"start_dev_runner 실패: {exc}")
        logger.error("[auto_dev_runner] failed to start plan=%s: %s", plan_id, exc)
        write_frontmatter_field(plan_path, "auto_run_status", "failed")

    write_frontmatter_field(plan_path, "auto_run_at", datetime.now().isoformat())
    result["ended_at"] = datetime.now().isoformat()
    return result


async def _scan_and_run_plans(today: date) -> list[dict]:
    eligible = _collect_eligible_plans(today)
    if not eligible:
        logger.info("[auto_dev_runner] no eligible plans for %s", today)
        return []

    logger.info("[auto_dev_runner] %d eligible plans: %s", len(eligible), [p.name for p in eligible])
    runs = []
    for plan_path in eligible:
        run_result = await _run_single_plan(plan_path, today)
        runs.append(run_result)
        _append_run_result(today, run_result)
    return runs


class AutoDevRunnerScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_AUTO_DEV_RUNNER

    def claim_run(
        self,
        db: "Session",
        schedule: TaskSchedule,
        svc: TaskScheduleService,
        ctx: WorkerContext,
    ) -> ClaimedRun | None:
        # 수동 실행 요청을 먼저 소비
        claimed = claim_pending_manual_run(db, schedule, svc, ctx, "auto_dev_runner")
        if claimed:
            return claimed

        last_run = svc.get_latest_run(schedule.id)
        last_run_at = last_run.started_at if last_run else None
        if not should_run_cron(schedule, last_run_at):
            return None

        if svc.has_active_run(schedule.id):
            logger.info("[auto_dev_runner] active run exists, skip schedule_id=%s", schedule.id)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="auto_dev_runner",
            config_snapshot={},
        )

    async def execute(
        self, schedule: TaskSchedule, claimed: ClaimedRun, ctx: WorkerContext
    ) -> HandlerRunOutcome:
        today = date.today()
        runs = await _scan_and_run_plans(today)
        completed = sum(1 for r in runs if r["status"] == "completed")
        failed = sum(1 for r in runs if r["status"] == "failed")
        skipped = sum(1 for r in runs if r["status"] == "skipped")
        logger.info(
            "[auto_dev_runner] done: total=%d completed=%d failed=%d skipped=%d",
            len(runs), completed, failed, skipped,
        )
        return HandlerRunOutcome(
            collected_count=len(runs),
            saved_count=completed,
            stop_reason="completed",
            config_snapshot_patch={
                "runs": len(runs),
                "completed": completed,
                "failed": failed,
                "skipped": skipped,
            },
        )
