"""Schedule/target_type policy gate for LLM profile routing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.task_schedule import TaskSchedule
from app.modules.claude_worker.models.llm_request import LLMScheduleProfilePolicy
from app.modules.claude_worker.services.execution_window_service import (
    DEFAULT_TIMEZONE,
    LLMExecutionWindowService,
    _is_allowed_at,
    _normalize_window,
)
from app.modules.claude_worker.services.profile_store import list_profiles


@dataclass(frozen=True)
class SchedulePolicyDecision:
    allowed: bool
    reason: str | None = None
    policy: LLMScheduleProfilePolicy | None = None
    next_available_at: datetime | None = None


class ScheduleProfilePolicyService:
    def __init__(self, db: Session):
        self.db = db

    def list(self) -> list[LLMScheduleProfilePolicy]:
        return (
            self.db.query(LLMScheduleProfilePolicy)
            .order_by(
                LLMScheduleProfilePolicy.schedule_id.is_(None),
                LLMScheduleProfilePolicy.schedule_id,
                LLMScheduleProfilePolicy.target_type,
                LLMScheduleProfilePolicy.engine,
                LLMScheduleProfilePolicy.profile_name,
            )
            .all()
        )

    def replace_all(self, items: list[dict[str, Any]]) -> list[LLMScheduleProfilePolicy]:
        policies = [self._build_policy(item) for item in items]
        self.db.query(LLMScheduleProfilePolicy).delete()
        for policy in policies:
            self.db.add(policy)
        self.db.commit()
        return self.list()

    def decide_for_request(
        self,
        *,
        request,
        engine: str,
        profile_name: str,
        now: datetime | None = None,
    ) -> SchedulePolicyDecision:
        schedule_id = self._request_schedule_id(request)
        target_type = getattr(request, "caller_type", None)
        policy = self._find_policy(
            schedule_id=schedule_id,
            target_type=target_type,
            engine=engine,
            profile_name=profile_name,
        )
        if policy is None:
            return SchedulePolicyDecision(True)
        if not policy.enabled:
            return SchedulePolicyDecision(False, "schedule_policy_off", policy)
        current = now or datetime.now()
        if not self._windows_allow(policy, current):
            return SchedulePolicyDecision(
                False,
                "schedule_policy_off",
                policy,
                self._next_allowed_at(policy, current),
            )
        return SchedulePolicyDecision(True, policy=policy)

    def policy_priority(self, request, engine: str, profile_name: str) -> int:
        policy = self._find_policy(
            schedule_id=self._request_schedule_id(request),
            target_type=getattr(request, "caller_type", None),
            engine=engine,
            profile_name=profile_name,
        )
        return policy.priority if policy else 0

    def _find_policy(
        self,
        *,
        schedule_id: int | None,
        target_type: str | None,
        engine: str,
        profile_name: str,
    ) -> LLMScheduleProfilePolicy | None:
        if schedule_id is not None:
            return (
                self.db.query(LLMScheduleProfilePolicy)
                .filter(
                    LLMScheduleProfilePolicy.schedule_id == schedule_id,
                    LLMScheduleProfilePolicy.engine == engine,
                    LLMScheduleProfilePolicy.profile_name == profile_name,
                )
                .first()
            )
        if target_type:
            return (
                self.db.query(LLMScheduleProfilePolicy)
                .filter(
                    LLMScheduleProfilePolicy.target_type == target_type,
                    LLMScheduleProfilePolicy.engine == engine,
                    LLMScheduleProfilePolicy.profile_name == profile_name,
                    LLMScheduleProfilePolicy.schedule_id.is_(None),
                )
                .first()
            )
        return None

    def _build_policy(self, item: dict[str, Any]) -> LLMScheduleProfilePolicy:
        schedule_id = item.get("schedule_id")
        target_type = (item.get("target_type") or "").strip() or None
        if schedule_id is None and target_type is None:
            raise ValueError("schedule_id or target_type is required")
        if schedule_id is not None and self.db.get(TaskSchedule, int(schedule_id)) is None:
            raise ValueError(f"schedule_id not found: {schedule_id}")

        engine = str(item.get("engine") or "").strip()
        profile_name = str(item.get("profile_name") or "").strip()
        if not any(p.engine == engine and p.name == profile_name for p in list_profiles(engine)):
            raise ValueError(f"profile not found: {engine}/{profile_name}")

        allowed_windows = item.get("allowed_windows") or []
        quiet_windows = item.get("quiet_windows") or []
        self._validate_windows(allowed_windows, quiet_windows)
        return LLMScheduleProfilePolicy(
            schedule_id=int(schedule_id) if schedule_id is not None else None,
            target_type=target_type,
            engine=engine,
            profile_name=profile_name,
            enabled=bool(item.get("enabled", True)),
            priority=int(item.get("priority", 0) or 0),
            allowed_windows=json.dumps(allowed_windows, ensure_ascii=False),
            quiet_windows=json.dumps(quiet_windows, ensure_ascii=False),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @staticmethod
    def _request_schedule_id(request) -> int | None:
        raw = getattr(request, "cli_options", None)
        if not raw:
            return None
        try:
            options = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, json.JSONDecodeError):
            return None
        value = options.get("schedule_id") if isinstance(options, dict) else None
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _validate_windows(allowed_windows: list[dict], quiet_windows: list[dict]) -> None:
        LLMExecutionWindowService.validate_config(
            {
                "timezone": DEFAULT_TIMEZONE,
                "allowed_windows": allowed_windows,
                "quiet_windows": quiet_windows,
            }
        )

    @staticmethod
    def _windows_allow(policy: LLMScheduleProfilePolicy, now: datetime | None) -> bool:
        current = now or datetime.now()
        allowed_raw = json.loads(policy.allowed_windows or "[]")
        quiet_raw = json.loads(policy.quiet_windows or "[]")
        allowed = [_normalize_window(item) for item in allowed_raw]
        quiet = [_normalize_window(item) for item in quiet_raw]
        return _is_allowed_at(current, allowed, quiet)

    @staticmethod
    def _next_allowed_at(policy: LLMScheduleProfilePolicy, now: datetime) -> datetime | None:
        return LLMExecutionWindowService().next_allowed_at(
            now,
            {
                "timezone": DEFAULT_TIMEZONE,
                "allowed_windows": json.loads(policy.allowed_windows or "[]"),
                "quiet_windows": json.loads(policy.quiet_windows or "[]"),
            },
        )
