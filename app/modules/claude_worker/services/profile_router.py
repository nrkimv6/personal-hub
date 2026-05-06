"""LLM profile capacity router."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import LLMRequestProfileClaim
from app.modules.claude_worker.services.execution_window_service import LLMExecutionWindowService
from app.modules.claude_worker.services.llm_quota_service import LLMQuotaService
from app.modules.claude_worker.services.profile_store import LLMProfile, get_selected, list_profiles
from app.modules.claude_worker.services.repositories import LLMRequestRepository, LLMWorkerRepository
from app.modules.claude_worker.services.provider_registry import get_provider
from app.modules.claude_worker.services.schedule_profile_policy_service import ScheduleProfilePolicyService


@dataclass
class ProfileRouteDecision:
    profile: Optional[LLMProfile]
    reason: str
    next_available_at: Optional[datetime] = None
    blocked_counts: dict[str, int] | None = None


class LLMProfileRouter:
    def __init__(self, db: Session):
        self.db = db
        self.quota = LLMQuotaService(LLMRequestRepository(db), LLMWorkerRepository(db), db)
        self.execution_window = LLMExecutionWindowService()
        self.policy = ScheduleProfilePolicyService(db)

    def select_profile(self, engine: str, model: str = "", request=None) -> ProfileRouteDecision:
        provider = get_provider(engine)
        if provider is None or not provider.enabled:
            return ProfileRouteDecision(None, "provider_disabled")

        window = self.execution_window.decide()
        if not window.allowed:
            return ProfileRouteDecision(None, "outside_window", window.next_allowed_at)

        provider_pause = self.quota.get_provider_quota_pause(engine)
        if provider_pause:
            return ProfileRouteDecision(
                None,
                "all_paused_by_quota",
                provider_pause,
                {"quota": len(list_profiles(engine))},
            )

        profiles = list_profiles(engine)
        if not profiles:
            return ProfileRouteDecision(get_selected(engine), "fallback_selected")

        enabled = [p for p in profiles if p.enabled]
        candidates = self._candidate_profile_names(request, engine)
        if candidates is not None:
            enabled = [p for p in enabled if p.name in candidates]
        if not enabled:
            return ProfileRouteDecision(None, "no_enabled_profile", None, {"disabled": len(profiles)})

        available: list[LLMProfile] = []
        paused_count = 0
        policy_count = 0
        policy_next_times: list[datetime] = []
        for profile in enabled:
            if self.quota.get_profile_quota_pause(engine, profile.name):
                paused_count += 1
                continue
            if self._active_count(engine, profile.name) >= max(1, int(profile.capacity or 1)):
                policy_count += 1
                continue
            policy_decision = self.policy.decide_for_request(
                request=request,
                engine=engine,
                profile_name=profile.name,
            )
            if not policy_decision.allowed:
                policy_count += 1
                if policy_decision.next_available_at is not None:
                    policy_next_times.append(policy_decision.next_available_at)
                continue
            available.append(profile)

        if not available:
            next_times = [
                self.quota.get_profile_quota_pause(engine, profile.name)
                for profile in enabled
            ] + policy_next_times
            next_available = min([t for t in next_times if t is not None], default=None)
            return ProfileRouteDecision(
                None,
                "schedule_policy_off" if policy_count else "all_paused_by_quota",
                next_available,
                {"quota": paused_count, "policy": policy_count},
            )

        available.sort(
            key=lambda p: (
                -self.policy.policy_priority(request, engine, p.name),
                -p.priority,
                p.capacity,
                p.last_reset_at or datetime.min,
                p.name,
            )
        )
        return ProfileRouteDecision(available[0], "selected")

    def _active_count(self, engine: str, profile_name: str) -> int:
        return (
            self.db.query(LLMRequestProfileClaim)
            .filter(
                LLMRequestProfileClaim.engine == engine,
                LLMRequestProfileClaim.profile_name == profile_name,
            )
            .count()
        )

    @staticmethod
    def _candidate_profile_names(request, engine: str) -> set[str] | None:
        raw_options = getattr(request, "cli_options", None)
        if not raw_options:
            return None
        try:
            options = json.loads(raw_options) if isinstance(raw_options, str) else raw_options
        except (TypeError, json.JSONDecodeError):
            return None
        raw_candidates = options.get("candidate_profiles") if isinstance(options, dict) else None
        if not isinstance(raw_candidates, list):
            return None
        names = {
            str(item.get("profile_name") or item.get("name") or "").strip()
            for item in raw_candidates
            if isinstance(item, dict) and str(item.get("engine") or "").strip() == engine
        }
        return {name for name in names if name}
