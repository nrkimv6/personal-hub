"""워커 생사 판정용 Redis 헬스 유틸리티.

워커가 15초마다 Redis에 TTL=30초 키를 publish하여 생사를 알린다.
소비처(API, 대시보드)는 Redis TTL을 기반으로 워커 상태를 판정한다.
Redis 불가 시 PID 존재 확인으로 fallback한다.
"""
import json
import logging
import os
from datetime import datetime
from typing import Optional

import psutil

from app.shared.redis.client import RedisClient

logger = logging.getLogger(__name__)

HEALTH_KEY_PREFIX = "worker:health:"
DEFAULT_TTL = 30
PUBLISH_INTERVAL = 15

KNOWN_WORKER_TYPES = ["naver", "scheduled", "ondemand", "claude"]


class WorkerHealthRedis:
    """워커 생사 판정용 Redis 헬스 유틸리티.

    싱글톤 불필요 — 모든 메서드를 클래스 메서드 또는 모듈 수준 함수로 제공한다.
    """

    @classmethod
    def publish(
        cls,
        worker_type: str,
        pid: int,
        state: str,
        memory_mb: float = 0,
        active_tasks: int = 0,
    ) -> bool:
        """워커 헬스 정보를 Redis에 publish한다.

        Args:
            worker_type: 워커 타입 (naver, scheduled, ondemand, claude)
            pid: 워커 프로세스 PID
            state: 워커 상태 (running, idle 등)
            memory_mb: 메모리 사용량 (MB)
            active_tasks: 현재 처리 중인 작업 수

        Returns:
            True if publish succeeded, False otherwise (silent fail)
        """
        try:
            client = RedisClient.get_sync_client()
            if client is None:
                logger.warning(f"[WorkerHealthRedis] Redis 클라이언트 없음, publish 스킵: {worker_type}")
                return False

            key = f"{HEALTH_KEY_PREFIX}{worker_type}"
            value = json.dumps({
                "pid": pid,
                "state": state,
                "memory_mb": memory_mb,
                "active_tasks": active_tasks,
                "updated_at": datetime.now().isoformat(),
            })
            client.set(key, value, ex=DEFAULT_TTL)
            return True
        except Exception as e:
            logger.warning(f"[WorkerHealthRedis] publish 실패: {e}")
            return False

    @classmethod
    def check(
        cls,
        worker_type: str,
        pid: Optional[int] = None,
        started_at: Optional[datetime] = None,
    ) -> Optional[dict]:
        """워커 헬스 정보를 Redis에서 조회한다.

        Args:
            worker_type: 워커 타입
            pid: PID fallback용 (Redis 불가 또는 키 없을 때 PID 존재 확인)
            started_at: PID 재활용 감지용 시작 시각

        Returns:
            dict with keys: pid, state, memory_mb, active_tasks, updated_at,
                            ttl_remaining, source ("redis" or "pid_only")
            None if worker is dead or info unavailable
        """
        try:
            client = RedisClient.get_sync_client()
            if client is None:
                return cls._pid_fallback(worker_type, pid, started_at)

            key = f"{HEALTH_KEY_PREFIX}{worker_type}"
            raw = client.get(key)
            if raw is None:
                return cls._pid_fallback(worker_type, pid, started_at)

            ttl = client.ttl(key)
            data = json.loads(raw)
            data["ttl_remaining"] = max(ttl, 0)
            data["source"] = "redis"
            return data
        except Exception as e:
            logger.warning(f"[WorkerHealthRedis] check 실패: {e}")
            return cls._pid_fallback(worker_type, pid, started_at)

    @classmethod
    def _pid_fallback(
        cls,
        worker_type: str,
        pid: Optional[int],
        started_at: Optional[datetime],
    ) -> Optional[dict]:
        """Redis 불가 시 PID 존재 확인으로 fallback."""
        if pid is None:
            return None
        alive = check_pid_alive(pid, started_at)
        return {
            "pid": pid,
            "alive": alive,
            "source": "pid_only",
            "ttl_remaining": 0,
        }

    @classmethod
    def check_all(cls) -> dict:
        """모든 알려진 워커 타입의 헬스 정보를 한 번에 조회한다.

        Returns:
            {worker_type: dict | None} 형태의 dict
        """
        return {wt: cls.check(wt) for wt in KNOWN_WORKER_TYPES}

    @classmethod
    def delete(cls, worker_type: str) -> None:
        """워커 헬스 키를 Redis에서 즉시 삭제한다 (워커 종료 시 사용)."""
        try:
            client = RedisClient.get_sync_client()
            if client is None:
                return
            client.delete(f"{HEALTH_KEY_PREFIX}{worker_type}")
        except Exception as e:
            logger.warning(f"[WorkerHealthRedis] delete 실패: {e}")


def check_pid_alive(pid: int, started_at: Optional[datetime] = None) -> bool:
    """PID가 살아있는 프로세스를 가리키는지 확인한다.

    Args:
        pid: 확인할 프로세스 PID
        started_at: 워커 시작 시각 (PID 재활용 감지용). None이면 create_time 비교 스킵.

    Returns:
        True if process is alive and matches started_at (if provided)
    """
    if not psutil.pid_exists(pid):
        return False
    try:
        process = psutil.Process(pid)
        if not process.is_running():
            return False
        if process.status() == psutil.STATUS_ZOMBIE:
            return False
        if started_at is not None:
            create_time_epoch = process.create_time()
            started_at_epoch = started_at.timestamp()
            if abs(create_time_epoch - started_at_epoch) > 5:
                return False
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
