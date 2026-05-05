"""LLMQuotaService — provider quota pause 상태 관리.

DB 접근: LLMRequestRepository, LLMWorkerRepository 경유.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("claude_worker.llm_quota_service")

# Quota pause 기본 대기 시간 (ms) — 6시간
QUOTA_PAUSE_DEFAULT_MS = 6 * 60 * 60 * 1000


def _summarize_quota_reason(provider: str, reason: str, paused_until: datetime) -> str:
    text = (reason or "").strip().replace("\r", " ").replace("\n", " ")
    if not text:
        return f"{provider} quota pause until {paused_until.isoformat(timespec='minutes')}"
    if "rate_limit" in text or "quota" in text.lower() or "capacity" in text.lower():
        prefix = f"{provider} quota pause until {paused_until.isoformat(timespec='minutes')}"
        return f"{prefix}: {text[:240]}"
    return text[:240]


class LLMQuotaService:
    """provider quota pause 상태 관리."""

    def __init__(self, repo, worker_repo, db: Session):
        self._repo = repo
        self._worker_repo = worker_repo
        self.db = db

    def set_provider_quota_pause(self, provider: str, retry_after_ms: int, reason: str = "") -> "datetime":
        """provider quota pause 상태 DB 저장.

        모든 활성 worker_status 레코드에 저장 (quota는 시스템 전역 상태).

        Returns:
            paused_until datetime
        """
        paused_until = datetime.now() + timedelta(milliseconds=retry_after_ms)
        reason_summary = _summarize_quota_reason(provider, reason, paused_until)

        statuses = self._worker_repo.find_all()
        for status in statuses:
            status.quota_paused_provider = provider
            status.quota_paused_until = paused_until
            status.quota_pause_reason = reason_summary

        self.db.commit()
        return paused_until

    def set_profile_quota_pause(
        self,
        provider: str,
        profile_name: str,
        retry_after_ms: int,
        reason: str = "",
    ) -> "datetime":
        """profile 단위 quota pause 상태를 JSON profile metadata에 저장."""
        paused_until = datetime.now() + timedelta(milliseconds=retry_after_ms)
        reason_summary = _summarize_quota_reason(provider, reason, paused_until)
        from app.modules.claude_worker.services.profile_store import update_profile_state

        update_profile_state(
            provider,
            profile_name,
            last_quota_pause_until=paused_until,
            last_reset_at=paused_until,
            last_state="paused_by_quota",
            last_error_summary=reason_summary,
        )
        return paused_until

    def get_provider_quota_pause(self, provider: str) -> Optional["datetime"]:
        """provider quota pause 만료 시각 조회.

        만료되지 않은 경우 paused_until 반환, 만료/없으면 None.
        """
        status = self._worker_repo.find_quota_pause(provider)
        if status and status.quota_paused_until:
            if status.quota_paused_until > datetime.now():
                return status.quota_paused_until
        return None

    def get_profile_quota_pause(self, provider: str, profile_name: str) -> Optional["datetime"]:
        from app.modules.claude_worker.services.profile_store import get_by_name

        try:
            profile = get_by_name(provider, profile_name)
        except ValueError:
            return None
        paused_until = profile.last_quota_pause_until
        if paused_until and paused_until > datetime.now():
            return paused_until
        return None

    def is_paused(self, provider: str, profile_name: Optional[str] = None) -> bool:
        if self.get_provider_quota_pause(provider):
            return True
        if profile_name and self.get_profile_quota_pause(provider, profile_name):
            return True
        return False

    def get_provider_quota_pause_detail(self, provider: str) -> dict:
        """provider quota pause 상태와 UI 표시용 reason을 함께 반환."""
        status = self._worker_repo.find_quota_pause(provider)
        if not status or not status.quota_paused_until:
            return {"paused_until": None, "reason": None}
        if status.quota_paused_until <= datetime.now():
            return {"paused_until": None, "reason": status.quota_pause_reason}
        return {
            "paused_until": status.quota_paused_until,
            "reason": status.quota_pause_reason,
        }

    def clear_provider_quota_pause(self, provider: str) -> bool:
        """provider quota pause 수동 해제."""
        statuses = self._worker_repo.find_by_quota_provider(provider)
        if not statuses:
            return False
        for status in statuses:
            status.quota_paused_provider = None
            status.quota_paused_until = None
            status.quota_pause_reason = None
        self.db.commit()
        return True

    def clear_profile_quota_pause(self, provider: str, profile_name: str) -> bool:
        from app.modules.claude_worker.services.profile_store import get_by_name, update_profile_state

        try:
            profile = get_by_name(provider, profile_name)
        except ValueError:
            return False
        update_profile_state(
            provider,
            profile.name,
            last_quota_pause_until=None,
            last_reset_at=None,
            last_state="available" if profile.enabled else "disabled",
            last_error_summary=None,
        )
        return True

    def reset_quota_failed_requests(self, provider: str) -> int:
        """quota 에러로 실패한 요청을 pending으로 전환.

        Returns:
            전환된 요청 수
        """
        targets = self._repo.find_quota_failed(provider)
        count = 0
        for req in targets:
            req.status = "pending"
            req.error_message = None
            req.result = None
            req.raw_response = None
            req.processed_at = None
            count += 1
        if count:
            self.db.commit()
        return count

    def get_blocked_pending_count(self, provider: str) -> int:
        """pause 중인 provider로 막힌 pending 요청 수 조회."""
        return self._repo.count_blocked_by_provider(provider)
