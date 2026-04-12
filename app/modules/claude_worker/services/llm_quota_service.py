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

        statuses = self._worker_repo.find_all()
        for status in statuses:
            status.quota_paused_provider = provider
            status.quota_paused_until = paused_until
            status.quota_pause_reason = reason

        self.db.commit()
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
