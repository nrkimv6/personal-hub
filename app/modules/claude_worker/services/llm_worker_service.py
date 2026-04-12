"""LLMWorkerService — 워커 등록/헬스체크/상태 관리.

DB 접근: LLMWorkerRepository 경유.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import LLMWorkerStatus

logger = logging.getLogger("claude_worker.llm_worker_service")


class LLMWorkerService:
    """워커 등록/헬스체크/상태 관리."""

    def __init__(self, worker_repo, db: Session):
        self._worker_repo = worker_repo
        self.db = db

    def register_worker(self, worker_id: str, pid: int) -> LLMWorkerStatus:
        """워커 등록."""
        self._worker_repo.deactivate_all_alive()

        now = datetime.now()
        status = LLMWorkerStatus(
            worker_id=worker_id,
            pid=pid,
            started_at=now,
            last_heartbeat=now,
            current_state="idle",
            is_alive=True,
        )
        self._worker_repo.add(status)
        self.db.commit()
        self.db.refresh(status)
        return status

    def update_heartbeat(self, worker_id: str) -> None:
        """하트비트 업데이트."""
        status = self._worker_repo.get_by_worker_id(worker_id)
        if status:
            status.last_heartbeat = datetime.now()
            self.db.commit()

    def update_worker_state(
        self, worker_id: str, state: str, request_id: int = None
    ) -> None:
        """워커 상태 업데이트."""
        status = self._worker_repo.get_by_worker_id(worker_id)
        if status:
            status.current_state = state
            status.current_request_id = request_id
            self.db.commit()

    def increment_processed(self, worker_id: str) -> None:
        """처리 카운트 증가."""
        status = self._worker_repo.get_by_worker_id(worker_id)
        if status:
            status.processed_count += 1
            self.db.commit()

    def increment_error(self, worker_id: str) -> None:
        """에러 카운트 증가."""
        status = self._worker_repo.get_by_worker_id(worker_id)
        if status:
            status.error_count += 1
            self.db.commit()

    def mark_worker_dead(self, worker_id: str) -> None:
        """워커 종료 표시."""
        status = self._worker_repo.get_by_worker_id(worker_id)
        if status:
            status.is_alive = False
            status.current_state = "stopped"
            self.db.commit()

    def get_worker_status(self) -> Optional[LLMWorkerStatus]:
        """활성 워커 상태 조회."""
        return self._worker_repo.get_alive()

    def check_worker_health(self) -> dict:
        """워커 건강 상태 확인.

        Returns:
            dict with keys:
                - status: "healthy" | "warning" | "unhealthy" | "no_worker"
                - message: 상태 설명
                - worker_id: 워커 ID (있는 경우)
                - state: 현재 상태 (healthy/warning인 경우)
                - processed_count: 처리 건수 (healthy인 경우)
                - seconds_since_heartbeat: 마지막 heartbeat 이후 경과 시간
        """
        status = self.get_worker_status()
        if not status:
            return {"status": "no_worker", "message": "활성 워커 없음"}

        from app.shared.worker.health_redis import WorkerHealthRedis
        redis_health = WorkerHealthRedis.check("claude")

        if redis_health and redis_health.get("source") == "redis":
            ttl = redis_health.get("ttl_remaining", 0)
            seconds_since = max(0, 30 - ttl)

            if ttl <= 0:
                return {
                    "status": "unhealthy",
                    "message": "Redis heartbeat 만료 - 재시작 필요",
                    "worker_id": status.worker_id,
                    "seconds_since_heartbeat": int(seconds_since),
                }
            elif ttl <= 15:
                return {
                    "status": "warning",
                    "message": f"마지막 heartbeat {seconds_since:.0f}초 전 - 지연 발생",
                    "worker_id": status.worker_id,
                    "state": status.current_state,
                    "seconds_since_heartbeat": int(seconds_since),
                }
        else:
            return {
                "status": "unhealthy",
                "message": "Redis heartbeat 키 없음 - 재시작 필요",
                "worker_id": status.worker_id,
                "seconds_since_heartbeat": 999,
            }

        return {
            "status": "healthy",
            "worker_id": status.worker_id,
            "state": status.current_state,
            "processed_count": status.processed_count,
        }
