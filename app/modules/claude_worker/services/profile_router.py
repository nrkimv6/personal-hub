"""LLM profile capacity router."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.claude_worker.services.execution_window_service import LLMExecutionWindowService
from app.modules.claude_worker.services.llm_quota_service import LLMQuotaService
from app.modules.claude_worker.services.profile_store import LLMProfile, get_selected, list_profiles
from app.modules.claude_worker.services.repositories import LLMRequestRepository, LLMWorkerRepository
from app.modules.claude_worker.services.provider_registry import get_provider


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
        if not enabled:
            return ProfileRouteDecision(None, "no_enabled_profile", None, {"disabled": len(profiles)})

        available: list[LLMProfile] = []
        paused_count = 0
        for profile in enabled:
            if self.quota.get_profile_quota_pause(engine, profile.name):
                paused_count += 1
                continue
            available.append(profile)

        if not available:
            next_times = [
                self.quota.get_profile_quota_pause(engine, profile.name)
                for profile in enabled
            ]
            next_available = min([t for t in next_times if t is not None], default=None)
            return ProfileRouteDecision(
                None,
                "all_paused_by_quota",
                next_available,
                {"quota": paused_count},
            )

        available.sort(
            key=lambda p: (
                -p.priority,
                p.last_reset_at or datetime.min,
                p.name,
            )
        )
        return ProfileRouteDecision(available[0], "selected")
