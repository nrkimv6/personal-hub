"""LLMWorkerRepository — LLMWorkerStatus ORM 쿼리 전담."""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import LLMWorkerStatus


class LLMWorkerRepository:
    """LLMWorkerStatus DB 접근 단일 창구.

    commit/rollback은 Service 레벨(UoW 패턴)에서 수행.
    """

    def __init__(self, db: Session):
        self.db = db

    # ── 생성 ──────────────────────────────────────────────────────────────

    def add(self, status: LLMWorkerStatus) -> LLMWorkerStatus:
        """세션에 추가 (commit은 호출자 책임)."""
        self.db.add(status)
        return status

    # ── 단일 조회 ─────────────────────────────────────────────────────────

    def get_by_worker_id(self, worker_id: str) -> Optional[LLMWorkerStatus]:
        return (
            self.db.query(LLMWorkerStatus)
            .filter(LLMWorkerStatus.worker_id == worker_id)
            .first()
        )

    def get_alive(self) -> Optional[LLMWorkerStatus]:
        """활성 워커 상태 조회."""
        return (
            self.db.query(LLMWorkerStatus)
            .filter(LLMWorkerStatus.is_alive == True)
            .first()
        )

    # ── 목록 조회 ─────────────────────────────────────────────────────────

    def find_all(self) -> List[LLMWorkerStatus]:
        """모든 워커 상태 조회 (quota pause 시스템 전역 적용용)."""
        return self.db.query(LLMWorkerStatus).all()

    def find_by_quota_provider(self, provider: str) -> List[LLMWorkerStatus]:
        """특정 provider로 quota pause된 워커 상태 조회."""
        return (
            self.db.query(LLMWorkerStatus)
            .filter(LLMWorkerStatus.quota_paused_provider == provider)
            .all()
        )

    def find_quota_pause(self, provider: str) -> Optional[LLMWorkerStatus]:
        """특정 provider quota pause 상태 단일 조회."""
        return (
            self.db.query(LLMWorkerStatus)
            .filter(LLMWorkerStatus.quota_paused_provider == provider)
            .first()
        )

    # ── 업데이트 (벌크) ───────────────────────────────────────────────────

    def deactivate_all_alive(self) -> None:
        """모든 활성 워커를 비활성화 (register_worker 전처리)."""
        self.db.query(LLMWorkerStatus).filter(
            LLMWorkerStatus.is_alive == True
        ).update({"is_alive": False})
