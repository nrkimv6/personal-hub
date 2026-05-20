"""태스크 스케줄 서비스."""

from datetime import datetime, timedelta
from typing import Any, Optional, List
from sqlalchemy.orm import Session

from app.models import TaskSchedule, TaskScheduleRun
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService
from app.services.schedule_contracts import build_time_window_candidate_summary


def _merge_target_config(existing: Optional[dict], patch: dict) -> dict:
    """target_config patch를 병합한다.

    None / 빈 문자열 값은 해당 key 삭제로 해석한다.
    """
    merged = dict(existing or {})
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
            continue
        if isinstance(value, str):
            normalized = value.strip()
            if normalized == "":
                merged.pop(key, None)
                continue
            merged[key] = normalized
            continue
        merged[key] = value
    return merged


class TaskScheduleService:
    """태스크 스케줄 관리 서비스."""

    AUDIT_SOURCE_INHERIT = "inherit"
    AUDIT_SOURCE_CALLER_DEFAULT = "caller_default"
    AUDIT_SOURCE_SCHEDULE_PIN = "schedule_pin"
    AUDIT_SOURCE_LEGACY_PLACEHOLDER = "legacy_placeholder"

    AUDIT_TARGET_CALLER_MAP = {
        TaskSchedule.TARGET_TYPE_WRITING_TASK: "writing_generate",
        TaskSchedule.TARGET_TYPE_TOPIC_EXTRACT: "topic_extract",
        TaskSchedule.TARGET_TYPE_REPORT: "report",
        TaskSchedule.TARGET_TYPE_PYTEST_RUN: "pytest_fix",
        TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE: "plan_archive_analyze",
    }

    HEALTH_TARGET_TYPES = {
        TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
        TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH,
    }

    def __init__(self, db: Session):
        self.db = db

    def create_schedule(
        self,
        name: str,
        target_type: str,
        schedule_type: str,
        display_name: Optional[str] = None,
        target_config: Optional[dict] = None,
        schedule_value: Optional[str] = None,
        enabled: bool = True
    ) -> TaskSchedule:
        """새 스케줄 생성."""
        schedule = TaskSchedule(
            name=name,
            display_name=display_name,
            target_type=target_type,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            enabled=enabled
        )
        if target_config:
            schedule.set_target_config(target_config)

        self.db.add(schedule)
        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    def get_schedule_by_name(self, name: str) -> Optional[TaskSchedule]:
        """이름으로 스케줄 조회."""
        return self.db.query(TaskSchedule).filter(
            TaskSchedule.name == name
        ).first()

    def get_schedule_by_id(self, schedule_id: int) -> Optional[TaskSchedule]:
        """ID로 스케줄 조회."""
        return self.db.query(TaskSchedule).filter(
            TaskSchedule.id == schedule_id
        ).first()

    @staticmethod
    def _normalize_llm_value(value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        return value or None

    @classmethod
    def _audit_caller_type(cls, target_type: str) -> Optional[str]:
        return cls.AUDIT_TARGET_CALLER_MAP.get(target_type)

    def _resolve_runtime_llm(self, caller_type: str) -> tuple[str, str]:
        service = LLMService(self.db)
        try:
            return service.resolve_provider_model(caller_type, None, None)
        except Exception:
            defaults = service.load_llm_defaults()
            global_default = defaults.get("global_default", {})
            provider = self._normalize_llm_value(global_default.get("provider")) or "claude"
            model = self._normalize_llm_value(global_default.get("model")) or ""
            return provider, model

    def _build_schedule_audit(self, schedule: TaskSchedule, defaults: dict[str, Any]) -> dict[str, Any]:
        config = schedule.get_target_config() if schedule.target_config else {}
        provider = self._normalize_llm_value(config.get("llm_provider"))
        model = self._normalize_llm_value(config.get("llm_model"))
        caller_type = self._audit_caller_type(schedule.target_type)

        caller_defaults = defaults.get("caller_defaults", {}) if isinstance(defaults, dict) else {}
        caller_default = caller_defaults.get(caller_type, {}) if caller_type and isinstance(caller_defaults, dict) else {}
        caller_default_provider = self._normalize_llm_value(caller_default.get("provider"))
        caller_default_model = self._normalize_llm_value(caller_default.get("model"))

        legacy_placeholder = provider == "claude" and model is None and (
            "llm_provider" in config or "llm_model" in config
        )

        if provider and model and not legacy_placeholder:
            resolved_provider = provider
            resolved_model = model
            resolution_source = self.AUDIT_SOURCE_SCHEDULE_PIN
        elif legacy_placeholder:
            resolved_provider, resolved_model = self._resolve_runtime_llm(caller_type or schedule.target_type)
            resolution_source = self.AUDIT_SOURCE_LEGACY_PLACEHOLDER
        elif caller_default_provider and caller_default_model:
            resolved_provider = caller_default_provider
            resolved_model = caller_default_model
            resolution_source = self.AUDIT_SOURCE_CALLER_DEFAULT
        else:
            resolved_provider, resolved_model = self._resolve_runtime_llm(caller_type or schedule.target_type)
            resolution_source = self.AUDIT_SOURCE_INHERIT

        return {
            "resolved_provider": resolved_provider,
            "resolved_model": resolved_model,
            "resolution_source": resolution_source,
            "legacy_placeholder_candidate": legacy_placeholder,
            "caller_type": caller_type,
            "target_config": config,
        }

    def get_schedule_audit(self, include_disabled: bool = True) -> dict[str, Any]:
        """스케줄 LLM 감사 데이터 조회."""
        defaults_service = LLMService(self.db)
        defaults = defaults_service.load_llm_defaults()

        query = self.db.query(TaskSchedule)
        if not include_disabled:
            query = query.filter(TaskSchedule.enabled == True)

        schedules = query.order_by(TaskSchedule.target_type, TaskSchedule.name).all()
        items: list[dict[str, Any]] = []
        summary = {
            "total": 0,
            "enabled": 0,
            "schedule_pin": 0,
            "caller_default": 0,
            "inherit": 0,
            "legacy_placeholder": 0,
        }

        for schedule in schedules:
            audit = self._build_schedule_audit(schedule, defaults)
            summary["total"] += 1
            if schedule.enabled:
                summary["enabled"] += 1
            summary[audit["resolution_source"]] += 1

            items.append(
                {
                    "id": schedule.id,
                    "name": schedule.name,
                    "display_name": schedule.display_name,
                    "target_type": schedule.target_type,
                    "enabled": schedule.enabled,
                    "target_config": audit["target_config"],
                    "resolved_provider": audit["resolved_provider"],
                    "resolved_model": audit["resolved_model"],
                    "resolution_source": audit["resolution_source"],
                    "legacy_placeholder_candidate": audit["legacy_placeholder_candidate"],
                }
            )

        active_pin_count = sum(
            1
            for item in items
            if item["enabled"] and item["resolution_source"] == self.AUDIT_SOURCE_SCHEDULE_PIN
        )
        legacy_candidate_count = sum(
            1
            for item in items
            if item["enabled"] and item["legacy_placeholder_candidate"]
        )

        return {
            "items": items,
            "summary": {
                **summary,
                "active_pin_count": active_pin_count,
                "legacy_candidate_count": legacy_candidate_count,
            },
        }

    def get_schedule_health(self, schedule: TaskSchedule, *, days: int = 1) -> dict[str, Any]:
        """Return operational time-window health for crawl schedules."""
        if not schedule.enabled:
            return {
                "health": "ok",
                "reason": "disabled",
                "candidate_count": None,
                "requires_time_window_repair": False,
            }
        if schedule.schedule_type != TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW:
            return {
                "health": "ok",
                "reason": "not_time_window",
                "candidate_count": None,
                "requires_time_window_repair": False,
            }
        if schedule.target_type not in self.HEALTH_TARGET_TYPES:
            return {
                "health": "ok",
                "reason": "target_type_not_checked",
                "candidate_count": None,
                "requires_time_window_repair": False,
            }

        summary = build_time_window_candidate_summary(schedule.schedule_value, days=days)
        return {
            "health": summary["health"],
            "reason": summary["reason"],
            "candidate_count": summary["candidate_count"],
            "requires_time_window_repair": summary["has_exact_time_window"],
            "daily_runs": summary["daily_runs"],
            "time_window_count": summary["time_window_count"],
        }

    def get_scheduler_runtime_summary(self, recent_limit: int = 50) -> dict[str, Any]:
        """최근 scheduler 요청의 실제 provider/model 집계."""
        rows = (
            self.db.query(LLMRequest)
            .filter(LLMRequest.requested_by == "scheduler")
            .order_by(LLMRequest.requested_at.desc(), LLMRequest.id.desc())
            .limit(max(1, recent_limit))
            .all()
        )

        provider_map: dict[tuple[str, str], dict[str, Any]] = {}
        caller_map: dict[tuple[str, str, str], dict[str, Any]] = {}
        latest_request = None

        for req in rows:
            provider = self._normalize_llm_value(getattr(req, "provider", None)) or "claude"
            model = self._normalize_llm_value(getattr(req, "model", None)) or ""
            provider_key = (provider, model)
            provider_entry = provider_map.setdefault(
                provider_key,
                {
                    "provider": provider,
                    "model": model,
                    "count": 0,
                    "latest_requested_at": None,
                    "caller_types": set(),
                },
            )
            provider_entry["count"] += 1
            provider_entry["caller_types"].add(req.caller_type)
            if provider_entry["latest_requested_at"] is None or (
                req.requested_at and provider_entry["latest_requested_at"] < req.requested_at
            ):
                provider_entry["latest_requested_at"] = req.requested_at

            caller_key = (req.caller_type, provider, model)
            caller_entry = caller_map.setdefault(
                caller_key,
                {
                    "caller_type": req.caller_type,
                    "provider": provider,
                    "model": model,
                    "count": 0,
                    "latest_requested_at": None,
                },
            )
            caller_entry["count"] += 1
            if caller_entry["latest_requested_at"] is None or (
                req.requested_at and caller_entry["latest_requested_at"] < req.requested_at
            ):
                caller_entry["latest_requested_at"] = req.requested_at

            if latest_request is None:
                latest_request = req

        provider_summary = [
            {
                **entry,
                "caller_types": sorted(entry["caller_types"]),
            }
            for entry in sorted(
                provider_map.values(),
                key=lambda item: (-item["count"], item["provider"], item["model"]),
            )
        ]
        caller_summary = sorted(
            caller_map.values(),
            key=lambda item: (-item["count"], item["caller_type"], item["provider"], item["model"]),
        )

        return {
            "recent_limit": recent_limit,
            "total_requests": len(rows),
            "provider_summary": provider_summary,
            "caller_summary": caller_summary,
            "latest_request": (
                {
                    "id": latest_request.id,
                    "caller_type": latest_request.caller_type,
                    "caller_id": latest_request.caller_id,
                    "provider": latest_request.provider or "claude",
                    "model": latest_request.model or "",
                    "requested_at": latest_request.requested_at,
                    "requested_by": latest_request.requested_by,
                    "request_source": latest_request.request_source,
                }
                if latest_request
                else None
            ),
        }

    def preview_legacy_placeholder_repair(self, apply: bool = False) -> dict[str, Any]:
        """legacy placeholder 후보를 미리보기 또는 적용."""
        audit = self.get_schedule_audit(include_disabled=True)
        candidates = [
            item
            for item in audit["items"]
            if item["legacy_placeholder_candidate"]
        ]

        repaired_items: list[dict[str, Any]] = []
        for item in candidates:
            schedule = self.get_schedule_by_id(item["id"])
            if not schedule:
                continue
            config = schedule.get_target_config() if schedule.target_config else {}
            before = dict(config)
            after = dict(config)
            after.pop("llm_provider", None)
            after.pop("llm_model", None)
            repaired_items.append(
                {
                    "id": schedule.id,
                    "name": schedule.name,
                    "display_name": schedule.display_name,
                    "target_type": schedule.target_type,
                    "before": before,
                    "after": after,
                }
            )
            if apply:
                schedule.set_target_config(after)
                schedule.updated_at = datetime.now()

        if apply and repaired_items:
            self.db.commit()
            for item in repaired_items:
                schedule = self.get_schedule_by_id(item["id"])
                if schedule:
                    self.db.refresh(schedule)

        return {
            "dry_run": not apply,
            "candidate_count": len(candidates),
            "repaired_count": len(repaired_items) if apply else 0,
            "items": repaired_items,
        }

    def get_schedules_by_type(
        self,
        target_type: str,
        enabled_only: bool = True
    ) -> list[TaskSchedule]:
        """타입별 스케줄 조회."""
        query = self.db.query(TaskSchedule).filter(
            TaskSchedule.target_type == target_type
        )
        if enabled_only:
            query = query.filter(TaskSchedule.enabled == True)
        return query.all()

    def get_due_schedules(self) -> list[TaskSchedule]:
        """실행 대기 중인 스케줄 조회."""
        now = datetime.now()
        return self.db.query(TaskSchedule).filter(
            TaskSchedule.enabled == True,
            TaskSchedule.next_run_at <= now
        ).all()

    def update_schedule(
        self,
        schedule_id: int,
        **updates
    ) -> Optional[TaskSchedule]:
        """스케줄 업데이트."""
        schedule = self.get_schedule_by_id(schedule_id)
        if not schedule:
            return None

        for key, value in updates.items():
            if key == "target_config" and isinstance(value, dict):
                existing = schedule.get_target_config() if schedule.target_config else {}
                merged = _merge_target_config(existing, value)
                if merged:
                    schedule.set_target_config(merged)
                else:
                    schedule.target_config = None
            elif hasattr(schedule, key):
                setattr(schedule, key, value)

        schedule.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    def toggle_schedule(self, schedule_id: int, enabled: bool) -> Optional[TaskSchedule]:
        """스케줄 활성화/비활성화."""
        return self.update_schedule(schedule_id, enabled=enabled)

    def start_run(
        self,
        schedule_id: int,
        worker_id: Optional[str] = None,
        config_snapshot: Optional[dict] = None
    ) -> TaskScheduleRun:
        """스케줄 실행 시작."""
        run = TaskScheduleRun(
            schedule_id=schedule_id,
            started_at=datetime.now(),
            status=TaskScheduleRun.STATUS_RUNNING,
            worker_id=worker_id
        )
        if config_snapshot:
            run.set_config_snapshot(config_snapshot)

        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    @staticmethod
    def _snapshot_scheduled_for(run: TaskScheduleRun) -> Optional[datetime]:
        scheduled_for = run.get_config_snapshot().get("scheduled_for")
        if not isinstance(scheduled_for, str):
            return None
        try:
            return datetime.fromisoformat(scheduled_for)
        except ValueError:
            return None

    def get_or_create_deferred_run(
        self,
        schedule_id: int,
        scheduled_for: datetime,
        worker_id: Optional[str] = None,
        config_snapshot: Optional[dict] = None,
    ) -> TaskScheduleRun:
        """Create or reuse a deferred run for one scheduled slot."""
        for run in self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.schedule_id == schedule_id,
            TaskScheduleRun.status == TaskScheduleRun.STATUS_DEFERRED,
        ).all():
            if self._snapshot_scheduled_for(run) == scheduled_for:
                return run

        run = TaskScheduleRun(
            schedule_id=schedule_id,
            started_at=scheduled_for,
            status=TaskScheduleRun.STATUS_DEFERRED,
            worker_id=worker_id,
        )
        if config_snapshot:
            run.set_config_snapshot(config_snapshot)

        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_oldest_deferred_run(self, schedule_id: int) -> Optional[TaskScheduleRun]:
        """Return the oldest deferred run by scheduled slot time."""
        runs = self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.schedule_id == schedule_id,
            TaskScheduleRun.status == TaskScheduleRun.STATUS_DEFERRED,
        ).all()
        if not runs:
            return None
        return min(runs, key=lambda run: self._snapshot_scheduled_for(run) or run.started_at)

    def claim_deferred_run(self, run_id: int, worker_id: Optional[str] = None) -> Optional[TaskScheduleRun]:
        """Transition a deferred run into the normal running lifecycle."""
        run = self.get_run_by_id(run_id)
        if not run or run.status != TaskScheduleRun.STATUS_DEFERRED:
            return None
        run.status = TaskScheduleRun.STATUS_RUNNING
        run.started_at = datetime.now()
        run.finished_at = None
        run.worker_id = worker_id
        self.db.commit()
        self.db.refresh(run)
        return run

    def is_slot_claimed(self, schedule_id: int, scheduled_for: datetime) -> bool:
        """Return True if a scheduled slot is already running, deferred, or complete."""
        claimed_statuses = {
            TaskScheduleRun.STATUS_RUNNING,
            TaskScheduleRun.STATUS_DEFERRED,
            TaskScheduleRun.STATUS_COMPLETED,
        }
        runs = self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.schedule_id == schedule_id,
            TaskScheduleRun.status.in_(claimed_statuses),
        ).all()
        return any(self._snapshot_scheduled_for(run) == scheduled_for for run in runs)

    def complete_run(
        self,
        run_id: int,
        collected_count: int,
        saved_count: int,
        stop_reason: Optional[str] = None
    ) -> Optional[TaskScheduleRun]:
        """실행 완료 처리."""
        run = self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.id == run_id
        ).first()

        if run:
            run.mark_completed(collected_count, saved_count, stop_reason)
            self.db.commit()
            self.db.refresh(run)
        return run

    def fail_run(
        self,
        run_id: int,
        error_message: str
    ) -> Optional[TaskScheduleRun]:
        """실행 실패 처리."""
        run = self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.id == run_id
        ).first()

        if run:
            run.mark_failed(error_message)
            self.db.commit()
            self.db.refresh(run)
        return run

    def update_schedule_after_run(
        self,
        schedule_id: int,
        next_run_at: Optional[datetime] = None
    ):
        """실행 후 스케줄 상태 업데이트."""
        schedule = self.get_schedule_by_id(schedule_id)
        if schedule:
            schedule.update_last_run(next_run_at)
            self.db.commit()

    def get_runs_paginated(
        self,
        schedule_id: Optional[int] = None,
        page: int = 1,
        limit: int = 20,
        status: Optional[str] = None
    ) -> dict:
        """실행 이력 페이징 조회."""
        query = self.db.query(TaskScheduleRun)

        if schedule_id:
            query = query.filter(TaskScheduleRun.schedule_id == schedule_id)
        if status:
            query = query.filter(TaskScheduleRun.status == status)

        total = query.count()
        items = query.order_by(
            TaskScheduleRun.started_at.desc()
        ).offset((page - 1) * limit).limit(limit).all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }

    def get_latest_run(self, schedule_id: int) -> Optional[TaskScheduleRun]:
        """스케줄의 최신 실행 조회."""
        return self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.schedule_id == schedule_id
        ).order_by(TaskScheduleRun.started_at.desc()).first()

    def get_run_stats(
        self,
        schedule_id: Optional[int] = None,
        days: int = 7
    ) -> dict:
        """실행 통계 조회."""
        since = datetime.now() - timedelta(days=days)

        query = self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.started_at >= since
        )
        if schedule_id:
            query = query.filter(TaskScheduleRun.schedule_id == schedule_id)

        runs = query.all()

        total_runs = len(runs)
        completed_runs = sum(1 for r in runs if r.status == TaskScheduleRun.STATUS_COMPLETED)
        failed_runs = sum(1 for r in runs if r.status == TaskScheduleRun.STATUS_FAILED)
        total_collected = sum(r.collected_count or 0 for r in runs)
        total_saved = sum(r.saved_count or 0 for r in runs)

        return {
            "period_days": days,
            "total_runs": total_runs,
            "completed_runs": completed_runs,
            "failed_runs": failed_runs,
            "success_rate": completed_runs / total_runs * 100 if total_runs > 0 else 0,
            "total_collected": total_collected,
            "total_saved": total_saved
        }

    def has_active_run(self, schedule_id: int) -> bool:
        """활성 실행(running 상태)이 있는지 확인."""
        return self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.schedule_id == schedule_id,
            TaskScheduleRun.status == TaskScheduleRun.STATUS_RUNNING
        ).first() is not None

    def get_pending_manual_run(self, schedule_id: int) -> Optional[TaskScheduleRun]:
        """수동으로 생성된 대기 중인 실행 조회.

        API에서 수동 실행 시 worker_id='manual'로 생성된 run을 찾습니다.
        워커가 이 run을 감지하면 실제로 실행합니다.

        Args:
            schedule_id: 스케줄 ID

        Returns:
            수동으로 생성된 running 상태의 run (없으면 None)
        """
        return self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.schedule_id == schedule_id,
            TaskScheduleRun.status == TaskScheduleRun.STATUS_RUNNING,
            TaskScheduleRun.worker_id == "manual"
        ).order_by(TaskScheduleRun.started_at.asc()).first()

    def cleanup_stale_runs(self, timeout_minutes: int = 30) -> int:
        """오래된 running 상태 실행을 failed로 정리.

        워커가 비정상 종료되면 running 상태로 남을 수 있음.

        Args:
            timeout_minutes: running 상태 유지 시간 제한

        Returns:
            정리된 실행 수
        """
        cutoff = datetime.now() - timedelta(minutes=timeout_minutes)

        stale_runs = self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.status == TaskScheduleRun.STATUS_RUNNING,
            TaskScheduleRun.started_at < cutoff
        ).all()

        count = 0
        for run in stale_runs:
            run.mark_failed(f"Timeout: running 상태가 {timeout_minutes}분 초과")
            count += 1

        if count > 0:
            self.db.commit()

        return count

    def update_run_progress(
        self,
        run_id: int,
        collected_count: int,
        saved_count: int
    ):
        """실행 중간 진행 상황 업데이트."""
        run = self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.id == run_id
        ).first()

        if run:
            run.collected_count = collected_count
            run.saved_count = saved_count
            self.db.commit()

    def get_all_schedules(
        self,
        target_type: Optional[str] = None,
        enabled_only: bool = False
    ) -> List[TaskSchedule]:
        """모든 스케줄 조회."""
        query = self.db.query(TaskSchedule)

        if target_type:
            query = query.filter(TaskSchedule.target_type == target_type)
        if enabled_only:
            query = query.filter(TaskSchedule.enabled == True)

        return query.order_by(TaskSchedule.created_at.desc()).all()

    def get_run_by_id(self, run_id: int) -> Optional[TaskScheduleRun]:
        """실행 ID로 조회."""
        return self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.id == run_id
        ).first()

    def delete_schedule(self, schedule_id: int, delete_runs: bool = False) -> bool:
        """스케줄 삭제.

        Args:
            schedule_id: 삭제할 스케줄 ID
            delete_runs: True면 실행 이력도 함께 삭제, False면 이력 유지

        Returns:
            삭제 성공 여부
        """
        schedule = self.get_schedule_by_id(schedule_id)
        if not schedule:
            return False

        if delete_runs:
            # 실행 이력도 함께 삭제
            self.db.query(TaskScheduleRun).filter(
                TaskScheduleRun.schedule_id == schedule_id
            ).delete()

        self.db.delete(schedule)
        self.db.commit()
        return True

    def get_run_count(self, schedule_id: int) -> int:
        """스케줄의 실행 이력 수 조회."""
        return self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.schedule_id == schedule_id
        ).count()


# 하위 호환성 별칭 (deprecated - 향후 제거 예정)
CrawlScheduleService = TaskScheduleService
