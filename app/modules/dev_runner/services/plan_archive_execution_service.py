"""Plan Archive execution job/attempt service."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.models.plan_archive_execution import PlanArchiveExecutionAttempt, PlanArchiveExecutionJob
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMProfileAssignment, LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.services.plan_archive_prompt_policy import (
    DEFAULT_CATEGORIES,
    PromptPolicyContext,
    build_plan_archive_prompt,
)
from app.modules.dev_runner.services.plan_record_service import _is_temp_pytest_path


JOB_ACTIVE_STATUSES = {"pending", "queued", "processing", "blocked"}
JOB_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ATTEMPT_RETRYABLE_STATUSES = {"blocked", "retryable"}


def _profiles_to_snapshot(selected_profiles: list[dict[str, str]] | None) -> list[dict[str, str]]:
    snapshot: list[dict[str, str]] = []
    for item in selected_profiles or []:
        engine = str(item.get("engine") or "").strip()
        profile_name = str(item.get("profile_name") or item.get("name") or "").strip()
        if engine and profile_name:
            snapshot.append({"engine": engine, "profile_name": profile_name})
    return snapshot


def _target_dedupe_key(
    *,
    provider: str,
    model: str | None = None,
    profile_key: str | None = None,
    engine: str | None = None,
    profile_name: str | None = None,
) -> str:
    model_key = (model or "").strip() or "default"
    if profile_key:
        return f"profile:{profile_key}:{model_key}"
    if engine and profile_name:
        return f"profile:{engine}:{profile_name}:{model_key}"
    provider_key = (provider or "").strip() or "unknown"
    return f"profileless:{provider_key}:{model_key}"


def _target_label(target: dict[str, Any]) -> str | None:
    raw = target.get("label")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    model = str(target.get("model") or "").strip()
    engine = str(target.get("engine") or "").strip()
    profile_name = str(target.get("profile_name") or "").strip()
    provider = str(target.get("provider") or "").strip()
    if engine and profile_name:
        return f"{engine}/{profile_name}/{model or 'default'}"
    if provider:
        return f"{provider}/{model or 'default'}"
    return None


def _target_cli_snapshot(target: dict[str, Any], *, provider: str | None = None, model: str | None = None) -> dict[str, Any]:
    resolved_provider = provider if provider is not None else target.get("provider")
    resolved_model = model if model is not None else target.get("model")
    return {
        "provider": resolved_provider,
        "model": resolved_model,
        "profile_key": target.get("profile_key"),
        "engine": target.get("engine"),
        "profile_name": target.get("profile_name"),
        "label": target.get("label"),
        "dedupe_key": target.get("dedupe_key"),
    }


def _request_cli_options(request: LLMRequest | None) -> dict[str, Any]:
    if request is None or not request.cli_options:
        return {}
    try:
        parsed = json.loads(request.cli_options)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _requested_target_from_cli(cli: dict[str, Any]) -> dict[str, Any]:
    raw = cli.get("requested_target")
    if isinstance(raw, dict):
        return raw
    profile_key = cli.get("profile_key") if isinstance(cli.get("profile_key"), str) else None
    target_label = cli.get("target_label") if isinstance(cli.get("target_label"), str) else None
    engine = None
    profile_name = None
    cps = cli.get("candidate_profiles")
    if isinstance(cps, list) and cps:
        first = cps[0] if isinstance(cps[0], dict) else None
        if first:
            engine = str(first.get("engine") or "").strip() or None
            profile_name = str(first.get("profile_name") or "").strip() or None
    return {
        "profile_key": profile_key,
        "engine": engine,
        "profile_name": profile_name,
        "label": target_label,
    }


def _targets_to_snapshot(
    selected_targets: list | None,
    selected_profiles: list[dict[str, str]] | None = None,
) -> list[dict]:
    """selected_targets 와 legacy selected_profiles 를 단일 target snapshot 으로 정규화.

    selected_targets 가 있으면 우선 사용, 없으면 legacy profiles 를 변환한다.
    각 항목에 dedupe_key 가 계산되어 포함된다.
    """
    if selected_targets:
        result = []
        for t in selected_targets:
            if hasattr(t, "model_dump"):
                d = t.model_dump()
            elif hasattr(t, "dict"):
                d = t.dict()
            elif isinstance(t, dict):
                d = dict(t)
            else:
                continue
            provider = str(d.get("provider") or "").strip()
            if not provider:
                continue
            model = str(d.get("model") or "").strip()
            profile_key = str(d.get("profile_key") or "").strip() or None
            engine = str(d.get("engine") or "").strip() or None
            profile_name = str(d.get("profile_name") or "").strip() or None
            dk = _target_dedupe_key(
                provider=provider,
                model=model,
                profile_key=profile_key,
                engine=engine,
                profile_name=profile_name,
            )
            item = {
                "provider": provider,
                "model": model,
                "profile_key": profile_key,
                "engine": engine,
                "profile_name": profile_name,
                "label": d.get("label"),
                "dedupe_key": dk,
            }
            item["label"] = _target_label(item)
            result.append(item)
        return result
    # legacy: profiles → target-like dicts
    result = []
    for item in selected_profiles or []:
        engine = str(item.get("engine") or "").strip()
        profile_name = str(item.get("profile_name") or item.get("name") or "").strip()
        if engine and profile_name:
            item = {
                "provider": engine,
                "model": "",
                "profile_key": None,
                "engine": engine,
                "profile_name": profile_name,
                "label": None,
                "dedupe_key": _target_dedupe_key(provider=engine, model="", engine=engine, profile_name=profile_name),
            }
            item["label"] = _target_label(item)
            result.append(item)
    return result


def _read_record_content(record: PlanRecord) -> str:
    if record.raw_content and record.raw_content.strip():
        return record.raw_content
    if not record.file_path:
        return ""
    try:
        path = Path(record.file_path)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return ""


class PlanArchiveExecutionService:
    def __init__(self, db: Session):
        self.db = db

    def enqueue_records(
        self,
        records: list[PlanRecord],
        *,
        trigger_source: str,
        selected_targets: list | None = None,
        selected_profiles: list[dict[str, str]] | None = None,
        requested_by: str = "api",
    ) -> dict[str, Any]:
        target_snapshot = _targets_to_snapshot(selected_targets, selected_profiles)
        stats = {
            "queued": 0,
            "skipped_empty": 0,
            "skipped_active_request": 0,
            "skipped_active_job": 0,
            "skipped_temp": 0,
            "profile_count": len(target_snapshot),
            "job_ids": [],
            "request_ids": [],
        }
        llm_service = LLMService(self.db)
        for record in records:
            result = self.enqueue_record(
                record,
                trigger_source=trigger_source,
                selected_targets=target_snapshot,
                requested_by=requested_by,
                llm_service=llm_service,
            )
            key = result.get("status_key")
            if key in stats:
                stats[key] += 1
            if result.get("job_id"):
                stats["job_ids"].append(result["job_id"])
            for rid in result.get("request_ids") or ([result["request_id"]] if result.get("request_id") else []):
                stats["request_ids"].append(rid)
        return stats

    def enqueue_record(
        self,
        record: PlanRecord,
        *,
        trigger_source: str,
        selected_targets: list | None = None,
        selected_profiles: list[dict[str, str]] | None = None,
        requested_by: str = "api",
        llm_service: LLMService | None = None,
        candidate_key: str | None = None,
        source_schedule_run_id: int | None = None,
    ) -> dict[str, Any]:
        # Normalize: selected_targets takes priority over legacy selected_profiles
        target_snapshot = _targets_to_snapshot(selected_targets, selected_profiles)
        # Build legacy profile list for _create_job backward compat
        legacy_profiles = [
            {"engine": t["engine"] or t["provider"], "profile_name": t["profile_name"] or ""}
            for t in target_snapshot
            if t.get("engine") or t.get("profile_name")
        ]

        if _is_temp_pytest_path(record.file_path):
            return {"status_key": "skipped_temp"}
        if self._has_active_job(record.id):
            return {"status_key": "skipped_active_job"}
        if self._has_active_request(record):
            return {"status_key": "skipped_active_request"}

        content = _read_record_content(record)
        if not content.strip():
            job = self._create_job(
                record,
                trigger_source=trigger_source,
                status="blocked",
                selected_profiles=legacy_profiles,
                profile_count=len(target_snapshot),
                error_message="EMPTY_PLAN_CONTENT",
            )
            self.db.flush()
            return {"status_key": "skipped_empty", "job_id": job.id}

        llm_service = llm_service or LLMService(self.db)

        # Resolve default provider/model from first target (or global default)
        first_target = target_snapshot[0] if target_snapshot else None
        provider_hint = (first_target["provider"] if first_target else None) or (
            legacy_profiles[0]["engine"] if legacy_profiles else None
        )
        default_provider, default_model = llm_service.resolve_provider_model(
            caller_type="plan_archive_analyze",
            provider=provider_hint,
            model=(first_target["model"] or None) if first_target else None,
        )

        prompt, policy_id, policy_version = build_plan_archive_prompt(
            PromptPolicyContext(
                caller_type="plan_archive_analyze",
                provider=default_provider,
                model=default_model,
                filename=Path(record.file_path).name,
                existing_categories=DEFAULT_CATEGORIES,
            ),
            content,
        )

        job = self._create_job(
            record,
            trigger_source=trigger_source,
            status="queued",
            selected_profiles=legacy_profiles,
            profile_count=len(target_snapshot),
        )
        self.db.flush()

        # Determine effective targets for fan-out
        effective_targets: list[dict] = target_snapshot or [{
            "provider": default_provider,
            "model": default_model,
            "profile_key": None,
            "engine": None,
            "profile_name": None,
            "label": None,
            "dedupe_key": f"profileless:{default_provider}:{default_model or 'default'}",
        }]

        # contract: caller_id = str(record.id) for plan_archive_analyze
        caller_id = str(record.id)
        request_ids: list[int] = []
        already_queued_count = 0

        for target in effective_targets:
            dedupe_key = target["dedupe_key"]
            t_provider, t_model = llm_service.resolve_provider_model(
                caller_type="plan_archive_analyze",
                provider=target["provider"] or None,
                model=target["model"] or None,
            )
            cli_options: dict = {
                "parse_json": True,
                "plan_archive_execution_job_id": job.id,
                "prompt_policy_id": policy_id,
                "prompt_policy_version": policy_version,
                "requested_target": _target_cli_snapshot(target),
                "effective_target": _target_cli_snapshot(target, provider=t_provider, model=t_model),
            }
            if candidate_key:
                cli_options["candidate_key"] = candidate_key
            if source_schedule_run_id:
                cli_options["source_schedule_run_id"] = source_schedule_run_id
            candidate_profiles: list = []
            if target.get("engine") and target.get("profile_name"):
                candidate_profiles = [{"engine": target["engine"], "profile_name": target["profile_name"]}]
            elif legacy_profiles:
                candidate_profiles = legacy_profiles
            if candidate_profiles:
                cli_options["candidate_profiles"] = candidate_profiles
            # Preserve selection identity for observability (UI may render this without parsing raw cli_options).
            if target.get("profile_key") is not None:
                cli_options["profile_key"] = target.get("profile_key")
            cli_options["target_label"] = target.get("label")

            request = LLMRequest(
                caller_type="plan_archive_analyze",
                caller_id=caller_id,
                prompt=prompt,
                queue_name="utility",
                requested_by=requested_by,
                request_source=trigger_source,
                provider=t_provider,
                model=t_model,
                dedupe_key=dedupe_key,
                cli_options=json.dumps(cli_options, ensure_ascii=False),
            )
            self.db.add(request)
            # Use savepoint so IntegrityError on dedupe doesn't abort the whole transaction
            sp = self.db.begin_nested()
            try:
                self.db.flush()
                sp.commit()
            except SAIntegrityError:
                sp.rollback()
                already_queued_count += 1
                continue

            request_ids.append(request.id)
            if not job.queued_at:
                job.queued_at = request.requested_at or datetime.now()
            job.latest_request_id = request.id

            attempt = PlanArchiveExecutionAttempt(
                job_id=job.id,
                llm_request_id=request.id,
                attempt_index=self._next_attempt_index(job.id),
                status="queued",
                provider=t_provider,
                model=t_model,
                requested_at=request.requested_at,
            )
            self.db.add(attempt)
            self.db.flush()

        if not request_ids:
            return {"status_key": "skipped_active_request", "job_id": job.id}

        return {
            "status_key": "queued",
            "job_id": job.id,
            "request_id": request_ids[0],
            "request_ids": request_ids,
        }

    def enqueue_unprocessed(
        self,
        *,
        include_temp_records: bool,
        max_backfill_per_run: int,
        trigger_source: str = "schedule:plan_archive_analyze",
        source_schedule_run_id: int | None = None,
    ) -> dict[str, Any]:
        stats = {
            "queued": 0,
            "skipped_temp": 0,
            "skipped_empty": 0,
            "skipped_active_request": 0,
            "skipped_active_job": 0,
            "remaining_real_unprocessed": 0,
            "profile_count": 0,
            "job_ids": [],
            "request_ids": [],
        }
        base_query = self.db.query(PlanRecord).filter(
            and_(
                PlanRecord.llm_processed_at.is_(None),
                PlanRecord.archived_at.isnot(None),
            )
        )
        all_unprocessed = base_query.order_by(PlanRecord.archived_at.asc()).all()
        real_candidates = [
            record
            for record in all_unprocessed
            if include_temp_records or not _is_temp_pytest_path(record.file_path)
        ]
        stats["skipped_temp"] = 0 if include_temp_records else len(all_unprocessed) - len(real_candidates)
        stats["remaining_real_unprocessed"] = len(real_candidates)
        for record in real_candidates[:max_backfill_per_run]:
            result = self.enqueue_record(
                record,
                trigger_source=trigger_source,
                requested_by="scheduler",
                source_schedule_run_id=source_schedule_run_id,
            )
            key = result.get("status_key")
            if key in stats:
                stats[key] += 1
            if result.get("job_id"):
                stats["job_ids"].append(result["job_id"])
            if result.get("request_id"):
                stats["request_ids"].append(result["request_id"])
        stats["remaining_real_unprocessed"] = max(
            stats["remaining_real_unprocessed"]
            - stats["queued"]
            - stats["skipped_active_request"]
            - stats["skipped_active_job"],
            0,
        )
        return stats

    def sync(self) -> dict[str, Any]:
        rows = self.db.query(PlanArchiveExecutionAttempt).filter(PlanArchiveExecutionAttempt.llm_request_id.isnot(None)).all()
        updated = 0
        for attempt in rows:
            if self.sync_attempt_for_request_id(attempt.llm_request_id, commit=False):
                updated += 1
        return {"updated": updated, "checked": len(rows), "errors": []}

    def sync_attempt_for_request_id(self, request_id: int, *, commit: bool = True) -> bool:
        request = self.db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
        attempt = (
            self.db.query(PlanArchiveExecutionAttempt)
            .filter(PlanArchiveExecutionAttempt.llm_request_id == request_id)
            .first()
        )
        if request is None or attempt is None:
            return False
        changed = self._sync_attempt_from_request(attempt, request)
        if changed:
            self._sync_job_from_attempt(attempt)
            if commit:
                self.db.commit()
        return changed

    def mark_request_profile(self, request_id: int, engine: str, profile_name: str) -> None:
        attempt = (
            self.db.query(PlanArchiveExecutionAttempt)
            .filter(PlanArchiveExecutionAttempt.llm_request_id == request_id)
            .first()
        )
        if attempt is None:
            return
        now = datetime.now()
        attempt.engine = engine
        attempt.profile_name = profile_name
        attempt.started_at = attempt.started_at or now
        attempt.status = "processing"
        attempt.job.status = "processing"
        attempt.job.started_at = attempt.job.started_at or now
        self.db.commit()

    def mark_request_blocked(
        self,
        request_id: int,
        reason: str,
        *,
        next_available_at: datetime | None = None,
    ) -> None:
        attempt = (
            self.db.query(PlanArchiveExecutionAttempt)
            .filter(PlanArchiveExecutionAttempt.llm_request_id == request_id)
            .first()
        )
        if attempt is None:
            return
        attempt.status = "blocked"
        attempt.retryable = 1
        attempt.error_message = reason
        attempt.job.status = "blocked"
        attempt.job.error_message = reason
        attempt.job.next_available_at = next_available_at
        self.db.commit()

    def attach_latest_summaries(self, records: list[PlanRecord]) -> None:
        if not records:
            return
        ids = [record.id for record in records]
        latest_jobs = self._latest_jobs_for_records(ids)
        latest_attempts = self._latest_attempts_for_jobs([job.id for job in latest_jobs.values()])
        for record in records:
            job = latest_jobs.get(record.id)
            if job is None:
                record.archive_state = "processed" if record.llm_processed_at else "unprocessed"
                record.execution_state = None
                record.latest_attempt = None
                record.next_available_at = None
                continue
            attempt = latest_attempts.get(job.id)
            record.archive_state = "processed" if record.llm_processed_at else "unprocessed"
            record.execution_state = job.status
            record.latest_attempt = self._attempt_to_dict(attempt) if attempt else None
            record.next_available_at = job.next_available_at

    def history(self, *, record_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = self.db.query(PlanArchiveExecutionJob).order_by(PlanArchiveExecutionJob.created_at.desc())
        if record_id is not None:
            query = query.filter(PlanArchiveExecutionJob.plan_record_id == record_id)
        jobs = query.limit(max(1, min(limit, 200))).all()
        attempts = self._latest_attempts_for_jobs([job.id for job in jobs])
        return [self._job_to_history_item(job, attempts.get(job.id)) for job in jobs]

    def _create_job(
        self,
        record: PlanRecord,
        *,
        trigger_source: str,
        status: str,
        selected_profiles: list[dict[str, str]],
        profile_count: int | None = None,
        error_message: str | None = None,
    ) -> PlanArchiveExecutionJob:
        now = datetime.now()
        job = PlanArchiveExecutionJob(
            plan_record_id=record.id,
            trigger_source=trigger_source,
            status=status,
            selected_profiles=selected_profiles or None,
            profile_count=len(selected_profiles) if profile_count is None else profile_count,
            error_message=error_message,
            created_at=now,
            updated_at=now,
            completed_at=now if status in JOB_TERMINAL_STATUSES else None,
        )
        self.db.add(job)
        return job

    def _has_active_job(self, plan_record_id: int) -> bool:
        return (
            self.db.query(PlanArchiveExecutionJob.id)
            .filter(
                PlanArchiveExecutionJob.plan_record_id == plan_record_id,
                PlanArchiveExecutionJob.status.in_(JOB_ACTIVE_STATUSES),
            )
            .first()
            is not None
        )

    def _has_active_request(self, record: PlanRecord | int, dedupe_key: str | None = None) -> bool:
        """record_id 및 legacy filename_hash 기준으로 활성 LLMRequest 존재 여부를 확인한다.

        dedupe_key 가 주어지면 해당 target 에 한정해서 체크한다.
        caller_id 계약: plan_archive_analyze → str(record.id)
        """
        if isinstance(record, PlanRecord):
            caller_ids = [str(record.id)]
            if record.filename_hash:
                caller_ids.append(record.filename_hash)
        else:
            caller_ids = [str(record)]
        q = self.db.query(LLMRequest.id).filter(
            LLMRequest.caller_type == "plan_archive_analyze",
            LLMRequest.caller_id.in_(caller_ids),
            LLMRequest.status.in_(["pending", "processing"]),
            LLMRequest.deleted_at.is_(None),
        )
        if dedupe_key is not None:
            q = q.filter(LLMRequest.dedupe_key == dedupe_key)
        return q.first() is not None

    def _next_attempt_index(self, job_id: int) -> int:
        value = (
            self.db.query(func.max(PlanArchiveExecutionAttempt.attempt_index))
            .filter(PlanArchiveExecutionAttempt.job_id == job_id)
            .scalar()
        )
        return int(value or 0) + 1

    def _sync_attempt_from_request(self, attempt: PlanArchiveExecutionAttempt, request: LLMRequest) -> bool:
        old = (attempt.status, attempt.error_message, attempt.finished_at)
        attempt.provider = request.provider
        attempt.model = request.model
        attempt.requested_at = request.requested_at
        if request.status == "processing":
            attempt.status = "processing"
            attempt.started_at = attempt.started_at or datetime.now()
        elif request.status == "completed":
            attempt.status = "completed"
            attempt.finished_at = request.processed_at or datetime.now()
            attempt.retryable = 0
        elif request.status == "failed":
            attempt.status = "failed"
            attempt.finished_at = request.processed_at or datetime.now()
            attempt.error_message = request.error_message
        elif request.status == "cancelled":
            attempt.status = "cancelled"
            attempt.finished_at = request.processed_at or datetime.now()
        else:
            attempt.status = request.status or attempt.status

        assignment = (
            self.db.query(LLMProfileAssignment)
            .filter(LLMProfileAssignment.request_id == request.id)
            .order_by(LLMProfileAssignment.selected_at.desc())
            .first()
        )
        if assignment:
            attempt.engine = assignment.engine
            attempt.profile_name = assignment.profile_name
            if assignment.error_summary and not attempt.error_message:
                attempt.error_message = assignment.error_summary
        return old != (attempt.status, attempt.error_message, attempt.finished_at)

    def _sync_job_from_attempt(self, attempt: PlanArchiveExecutionAttempt) -> None:
        job = attempt.job
        job.latest_request_id = attempt.llm_request_id
        job.updated_at = datetime.now()
        if attempt.status == "processing":
            job.status = "processing"
            job.started_at = job.started_at or attempt.started_at or datetime.now()
        elif attempt.status == "completed":
            job.status = "completed"
            job.completed_at = attempt.finished_at or datetime.now()
            job.error_message = None
        elif attempt.status == "failed":
            job.status = "failed"
            job.completed_at = attempt.finished_at or datetime.now()
            job.error_message = attempt.error_message
        elif attempt.status in {"blocked", "retryable"}:
            job.status = "blocked"
            job.error_message = attempt.error_message
        elif attempt.status == "cancelled":
            job.status = "cancelled"
            job.completed_at = attempt.finished_at or datetime.now()

    def _latest_jobs_for_records(self, record_ids: list[int]) -> dict[int, PlanArchiveExecutionJob]:
        if not record_ids:
            return {}
        rows = (
            self.db.query(PlanArchiveExecutionJob)
            .filter(PlanArchiveExecutionJob.plan_record_id.in_(record_ids))
            .order_by(PlanArchiveExecutionJob.plan_record_id, PlanArchiveExecutionJob.created_at.desc())
            .all()
        )
        result: dict[int, PlanArchiveExecutionJob] = {}
        for row in rows:
            result.setdefault(row.plan_record_id, row)
        return result

    def _latest_attempts_for_jobs(self, job_ids: list[int]) -> dict[int, PlanArchiveExecutionAttempt]:
        if not job_ids:
            return {}
        rows = (
            self.db.query(PlanArchiveExecutionAttempt)
            .filter(PlanArchiveExecutionAttempt.job_id.in_(job_ids))
            .order_by(PlanArchiveExecutionAttempt.job_id, PlanArchiveExecutionAttempt.created_at.desc())
            .all()
        )
        result: dict[int, PlanArchiveExecutionAttempt] = {}
        for row in rows:
            result.setdefault(row.job_id, row)
        return result

    def _attempt_to_dict(self, attempt: PlanArchiveExecutionAttempt | None) -> dict[str, Any] | None:
        if attempt is None:
            return None
        cli = _request_cli_options(attempt.request)
        requested = _requested_target_from_cli(cli)
        return {
            "id": attempt.id,
            "llm_request_id": attempt.llm_request_id,
            "status": attempt.status,
            "engine": attempt.engine,
            "profile_name": attempt.profile_name,
            "provider": attempt.provider,
            "model": attempt.model,
            "requested_provider": requested.get("provider") or attempt.provider,
            "requested_model": requested.get("model") if requested.get("model") is not None else attempt.model,
            "requested_engine": requested.get("engine"),
            "requested_profile_name": requested.get("profile_name"),
            "requested_profile_key": requested.get("profile_key"),
            "target_label": requested.get("label"),
            "retryable": bool(attempt.retryable),
            "error_message": attempt.error_message,
            "requested_at": attempt.requested_at,
            "started_at": attempt.started_at,
            "finished_at": attempt.finished_at,
        }

    def _job_to_history_item(
        self,
        job: PlanArchiveExecutionJob,
        attempt: PlanArchiveExecutionAttempt | None,
    ) -> dict[str, Any]:
        selected_targets = []
        for item in job.attempts or []:
            cli = _request_cli_options(item.request)
            requested = _requested_target_from_cli(cli)
            if requested:
                selected_targets.append(requested)
        return {
            "id": job.id,
            "record_id": job.plan_record_id,
            "plan_record_id": job.plan_record_id,
            "plan_title": job.record.title if job.record else None,
            "file_path": job.record.file_path if job.record else None,
            "trigger_source": job.trigger_source,
            "status": job.status,
            "selected_profiles": job.selected_profiles or [],
            "selected_targets": selected_targets,
            "profile_count": job.profile_count,
            "latest_request_id": job.latest_request_id,
            "next_available_at": job.next_available_at,
            "error_message": job.error_message,
            "created_at": job.created_at,
            "queued_at": job.queued_at,
            "requested_at": attempt.requested_at if attempt else job.queued_at,
            "started_at": attempt.started_at if attempt else job.started_at,
            "completed_at": attempt.finished_at if attempt else job.completed_at,
            "llm_request_id": attempt.llm_request_id if attempt else job.latest_request_id,
            "engine": attempt.engine if attempt else None,
            "profile_name": attempt.profile_name if attempt else None,
            "provider": attempt.provider if attempt else None,
            "model": attempt.model if attempt else None,
            "latest_attempt": self._attempt_to_dict(attempt),
        }

    # ------------------------------------------------------------------
    # Compatibility entry point: queue_analysis(record, provider, model, profile_key)
    # Used by /records/{id}/reanalyze. profile_key=None is allowed (codex 등
    # profile-less provider 지원).
    # ------------------------------------------------------------------
    CALLER_TYPE = "plan_archive_analyze"

    def queue_analysis(
        self,
        record: PlanRecord,
        provider: str,
        model: str = "",
        profile_key: Optional[str] = None,
    ) -> Tuple[LLMRequest, bool]:
        """archive record에 대해 LLM 분석 요청을 큐에 등록한다.

        profile-backed provider(claude/gemini)와 profile-less provider(codex 등)
        모두 동일한 인터페이스로 큐잉한다. profile_key가 None이어도 허용한다.

        기존 pending/processing 요청이 있으면 그 요청을 재사용한다.

        Returns:
            (LLMRequest, created): created=False면 기존 요청 재사용
        """
        from app.modules.claude_worker.services import provider_registry
        if not provider_registry.is_supported(provider):
            raise ValueError(f"unsupported provider: {provider!r}")

        filename_hash = record.filename_hash
        if not filename_hash:
            raise ValueError(f"record id={record.id} has no filename_hash")

        existing = (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == self.CALLER_TYPE,
                LLMRequest.caller_id == filename_hash,
                LLMRequest.provider == provider,
                LLMRequest.status.in_(["pending", "processing"]),
            )
            .first()
        )
        if existing:
            logger.info(
                "[exec-svc] 중복 요청 스킵: record_id=%s filename_hash=%s provider=%s request_id=%s",
                record.id, filename_hash[:8], provider, existing.id,
            )
            return existing, False

        try:
            path = Path(record.file_path)
            content = path.read_text(encoding="utf-8", errors="replace")
            filename_only = path.name
        except Exception:
            content = record.raw_content or ""
            filename_only = Path(record.file_path).name if record.file_path else "unknown.md"

        from app.modules.claude_worker.services.plan_analyze_handler import build_plan_analyze_prompt
        prompt = build_plan_analyze_prompt(file_content=content, filename=filename_only)

        cli_options: dict[str, Any] = {"parse_json": True}
        if profile_key is not None:
            cli_options["profile_key"] = profile_key
            cli_options["profile_optional"] = True

        req = LLMRequest(
            caller_type=self.CALLER_TYPE,
            caller_id=filename_hash,
            prompt=prompt,
            requested_by="api",
            request_source="manual_reanalyze",
            queue_name="utility",
            status="pending",
            provider=provider,
            model=model,
            cli_options=json.dumps(cli_options, ensure_ascii=False),
        )
        self.db.add(req)
        logger.info(
            "[exec-svc] 분석 요청 큐 등록: record_id=%s provider=%s model=%s profile_key=%s",
            record.id, provider, model or "(default)", profile_key,
        )
        return req, True
