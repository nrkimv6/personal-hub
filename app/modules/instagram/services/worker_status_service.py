"""Instagram Worker Status Service - 워커 상태 관리 서비스."""

import logging
from datetime import datetime, timedelta
from typing import Optional
import uuid
import os

from sqlalchemy.orm import Session

from app.shared.worker.health_redis import WorkerHealthRedis

from app.models import InstagramWorkerStatus, TaskScheduleRun, CrawlRequest

logger = logging.getLogger("instagram.worker_status")

# 헬스체크 기준 (초)
HEALTHY_THRESHOLD = 60      # 60초 이내: healthy
WARNING_THRESHOLD = 120     # 120초 이내: warning, 초과: dead


class WorkerStatusService:
    """Instagram 워커 상태 관리 서비스."""

    def __init__(self, db: Session):
        """
        Args:
            db: SQLAlchemy 세션
        """
        self.db = db

    def register_worker(self, worker_id: Optional[str] = None) -> InstagramWorkerStatus:
        """새 워커를 등록합니다.

        기존 alive 워커가 있으면 dead로 표시하고 새 워커를 등록합니다.
        또한 이전 워커 크래시로 인해 '실행중' 상태로 남은 orphaned run들을 정리합니다.

        Args:
            worker_id: 워커 ID (없으면 UUID 생성)

        Returns:
            등록된 워커 상태
        """
        if worker_id is None:
            worker_id = str(uuid.uuid4())

        now = datetime.now()

        # 기존 alive 워커들을 dead로 표시
        self.db.query(InstagramWorkerStatus).filter(
            InstagramWorkerStatus.is_alive == True
        ).update({"is_alive": False})

        # Orphaned 실행 기록 정리 (finished_at이 NULL인 레코드)
        orphaned_count = self._cleanup_orphaned_runs()

        # 새 워커 등록
        worker_status = InstagramWorkerStatus(
            worker_id=worker_id,
            pid=os.getpid(),
            started_at=now,
            last_heartbeat=now,
            current_state="idle",
            is_alive=True,
        )
        self.db.add(worker_status)
        self.db.commit()
        self.db.refresh(worker_status)

        logger.info(f"Worker registered: {worker_id} (PID: {worker_status.pid})")
        if orphaned_count > 0:
            logger.info(f"Cleaned up {orphaned_count} orphaned records (runs + requests)")

        return worker_status

    def _cleanup_orphaned_runs(self) -> int:
        """이전 워커 크래시로 인해 '실행중' 상태로 남은 orphaned run/request들을 정리합니다.

        - TaskScheduleRun: status가 'running'인 레코드들을 찾아 실패 처리
        - CrawlRequest: processing 상태인 레코드들을 찾아 실패 처리

        Returns:
            정리된 레코드 수
        """
        now = datetime.now()
        total_cleaned = 0

        # 1. Orphaned TaskScheduleRun 정리 (running 상태로 stuck된 것들)
        orphaned_runs = self.db.query(TaskScheduleRun).filter(
            TaskScheduleRun.status == TaskScheduleRun.STATUS_RUNNING
        ).all()

        for run in orphaned_runs:
            run.finished_at = now
            run.status = TaskScheduleRun.STATUS_FAILED
            run.error_message = "Worker crashed - marked as failed on restart"

        if orphaned_runs:
            self.db.flush()
            logger.info(f"Cleaned up {len(orphaned_runs)} orphaned crawl schedule runs")
        total_cleaned += len(orphaned_runs)

        # 2. Orphaned CrawlRequest 정리 (processing 상태로 stuck된 것들)
        orphaned_requests = self.db.query(CrawlRequest).filter(
            CrawlRequest.status == CrawlRequest.STATUS_PROCESSING
        ).all()

        for req in orphaned_requests:
            req.mark_failed("Worker crashed - marked as failed on restart")

        if orphaned_requests:
            self.db.flush()
            logger.info(f"Cleaned up {len(orphaned_requests)} orphaned crawl requests")
        total_cleaned += len(orphaned_requests)

        return total_cleaned

    def update_heartbeat(self, worker_id: str) -> Optional[InstagramWorkerStatus]:
        """워커의 heartbeat를 업데이트합니다.

        Args:
            worker_id: 워커 ID

        Returns:
            업데이트된 워커 상태 (없으면 None)
        """
        worker = self.db.query(InstagramWorkerStatus).filter(
            InstagramWorkerStatus.worker_id == worker_id
        ).first()

        if worker:
            worker.last_heartbeat = datetime.now()
            self.db.commit()

        return worker

    def update_state(
        self,
        worker_id: str,
        state: str,
        account: Optional[str] = None,
        run_id: Optional[int] = None
    ) -> Optional[InstagramWorkerStatus]:
        """워커의 상태를 업데이트합니다.

        Args:
            worker_id: 워커 ID
            state: 상태 ('idle', 'crawling', 'processing')
            account: 현재 처리 중인 계정
            run_id: 현재 실행 중인 crawl_run_id

        Returns:
            업데이트된 워커 상태 (없으면 None)
        """
        worker = self.db.query(InstagramWorkerStatus).filter(
            InstagramWorkerStatus.worker_id == worker_id
        ).first()

        if worker:
            worker.current_state = state
            worker.current_account = account
            worker.current_run_id = run_id
            self.db.commit()
            logger.debug(f"Worker state updated: {state}, account={account}")

        return worker

    def mark_dead(self, worker_id: str) -> Optional[InstagramWorkerStatus]:
        """워커를 종료 상태로 표시합니다.

        Args:
            worker_id: 워커 ID

        Returns:
            업데이트된 워커 상태 (없으면 None)
        """
        worker = self.db.query(InstagramWorkerStatus).filter(
            InstagramWorkerStatus.worker_id == worker_id
        ).first()

        if worker:
            worker.is_alive = False
            worker.current_state = "stopped"
            worker.current_account = None
            worker.current_run_id = None
            self.db.commit()
            logger.info(f"Worker marked as dead: {worker_id}")

        return worker

    def get_current_status(self) -> Optional[InstagramWorkerStatus]:
        """현재 활성 워커의 상태를 조회합니다.

        Returns:
            현재 활성 워커 상태 (없으면 None)
        """
        return self.db.query(InstagramWorkerStatus).filter(
            InstagramWorkerStatus.is_alive == True
        ).order_by(InstagramWorkerStatus.started_at.desc()).first()

    def check_health(self) -> dict:
        """워커 헬스체크를 수행합니다.

        Returns:
            헬스체크 결과 dict:
            - status: 'healthy', 'warning', 'dead', 'no_worker'
            - worker_id: 워커 ID (있으면)
            - last_heartbeat: 마지막 heartbeat 시간
            - heartbeat_age_seconds: heartbeat 경과 시간 (초)
            - current_state: 현재 상태
            - message: 상태 메시지
        """
        worker = self.get_current_status()

        if not worker:
            return {
                "status": "no_worker",
                "worker_id": None,
                "last_heartbeat": None,
                "heartbeat_age_seconds": None,
                "current_state": None,
                "message": "No active worker found",
            }

        # Redis TTL 기반 판정 (worker_type 필드 없으므로 scheduled/ondemand 순차 조회)
        redis_health = WorkerHealthRedis.check("scheduled") or WorkerHealthRedis.check("ondemand")

        if redis_health and redis_health.get("source") == "redis":
            ttl = redis_health.get("ttl_remaining", 0)
            if ttl > 15:
                status = "healthy"
                message = "Worker is running normally"
            elif ttl > 0:
                status = "warning"
                message = f"Worker heartbeat delayed (TTL: {ttl}s remaining)"
            else:
                status = "dead"
                message = "Worker appears to be dead (Redis key expired)"
            age_seconds = max(0, 30 - ttl)
            last_heartbeat = redis_health.get("updated_at") or worker.last_heartbeat
        else:
            status = "dead"
            message = "Worker appears to be dead (no Redis key)"
            age_seconds = 999
            last_heartbeat = worker.last_heartbeat

        return {
            "status": status,
            "worker_id": worker.worker_id,
            "last_heartbeat": last_heartbeat,
            "heartbeat_age_seconds": age_seconds,
            "current_state": worker.current_state,
            "message": message,
        }

    def get_status_with_computed_fields(self) -> Optional[dict]:
        """계산된 필드가 포함된 워커 상태를 조회합니다.

        Returns:
            워커 상태 dict (없으면 None):
            - 기본 필드들
            - uptime_seconds: 가동 시간 (초)
            - heartbeat_age_seconds: heartbeat 경과 시간 (초)
        """
        worker = self.get_current_status()

        if not worker:
            return None

        now = datetime.now()
        uptime_seconds = int((now - worker.started_at).total_seconds())

        # Redis TTL 기반 heartbeat_age_seconds
        redis_health = WorkerHealthRedis.check("scheduled") or WorkerHealthRedis.check("ondemand")
        if redis_health and redis_health.get("source") == "redis":
            ttl = redis_health.get("ttl_remaining", 0)
            heartbeat_age_seconds = max(0, 30 - ttl)
            last_heartbeat = redis_health.get("updated_at") or worker.last_heartbeat
        else:
            heartbeat_age_seconds = 999
            last_heartbeat = worker.last_heartbeat

        return {
            "worker_id": worker.worker_id,
            "pid": worker.pid,
            "started_at": worker.started_at,
            "last_heartbeat": last_heartbeat,
            "current_state": worker.current_state,
            "current_account": worker.current_account,
            "current_run_id": worker.current_run_id,
            "is_alive": worker.is_alive,
            "uptime_seconds": uptime_seconds,
            "heartbeat_age_seconds": heartbeat_age_seconds,
        }

    def cleanup_stale_workers(self, max_age_hours: int = 24) -> int:
        """오래된 dead 워커 기록을 정리합니다.

        Args:
            max_age_hours: 정리 기준 시간 (기본 24시간)

        Returns:
            삭제된 레코드 수
        """
        cutoff = datetime.now() - timedelta(hours=max_age_hours)

        deleted = self.db.query(InstagramWorkerStatus).filter(
            InstagramWorkerStatus.is_alive == False,
            InstagramWorkerStatus.started_at < cutoff
        ).delete()

        self.db.commit()

        if deleted > 0:
            logger.info(f"Cleaned up {deleted} stale worker records")

        return deleted
