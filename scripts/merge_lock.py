"""
Merge Lock 유틸리티 — Redis 기반 분산 lock (SETNX + FIFO 대기 큐)

Redis 키 구조:
  plan-runner:merge-lock          → lock 보유 runner_id (STRING, TTL 600초)
  plan-runner:merge-wait-queue    → 대기 중인 runner_id 목록 (LIST, FIFO)
"""

import time
import logging

logger = logging.getLogger(__name__)

MERGE_LOCK_KEY = "plan-runner:merge-lock"
MERGE_WAIT_QUEUE_KEY = "plan-runner:merge-wait-queue"
MERGE_LOCK_TTL = 600  # seconds


def acquire_merge_lock(redis_client, runner_id: str, timeout: int = 600) -> bool:
    """
    Merge lock을 획득한다 (SETNX + FIFO 대기 큐 조합).

    1. 대기 큐에 runner_id를 RPUSH (이미 있으면 스킵)
    2. 폴링: lock이 없거나 내 차례(큐 맨 앞)이면 SETNX 시도
    3. 성공 시 큐에서 제거 후 True 반환
    4. timeout 초 내 획득 실패 시 큐에서 제거 후 False 반환

    Args:
        redis_client: Redis 클라이언트 인스턴스
        runner_id: 현재 runner의 고유 ID (문자열)
        timeout: 최대 대기 시간 (초, 기본 600)

    Returns:
        True if lock acquired, False if timed out
    """
    # 대기 큐에 등록 (중복 방지: 이미 있으면 RPUSH 안 함)
    queue: list = redis_client.lrange(MERGE_WAIT_QUEUE_KEY, 0, -1)
    queue_str = [item.decode() if isinstance(item, bytes) else item for item in queue]
    if runner_id not in queue_str:
        redis_client.rpush(MERGE_WAIT_QUEUE_KEY, runner_id)
        logger.info(f"[merge-lock] {runner_id} 대기 큐 등록")

    deadline = time.time() + timeout
    poll_interval = 1.0  # seconds

    while time.time() < deadline:
        # 큐 맨 앞이 나인지 확인
        front_raw = redis_client.lindex(MERGE_WAIT_QUEUE_KEY, 0)
        front = front_raw.decode() if isinstance(front_raw, bytes) else front_raw

        if front == runner_id:
            # 내 차례 — lock 획득 시도
            acquired = redis_client.set(MERGE_LOCK_KEY, runner_id, nx=True, ex=MERGE_LOCK_TTL)
            if acquired:
                # 큐에서 제거
                redis_client.lrem(MERGE_WAIT_QUEUE_KEY, 1, runner_id)
                logger.info(f"[merge-lock] {runner_id} lock 획득 완료")
                return True

        time.sleep(poll_interval)

    # timeout — 큐에서 제거
    redis_client.lrem(MERGE_WAIT_QUEUE_KEY, 1, runner_id)
    logger.warning(f"[merge-lock] {runner_id} lock 획득 timeout ({timeout}s)")
    return False


def release_merge_lock(redis_client, runner_id: str) -> bool:
    """
    Merge lock을 해제한다 (소유자 확인 후 DEL).

    lock을 보유한 runner_id가 요청자와 일치할 때만 삭제한다.
    일치하지 않으면 (다른 runner가 획득했거나 이미 만료) False를 반환하고 아무 것도 하지 않는다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        runner_id: 현재 runner의 고유 ID (문자열)

    Returns:
        True if lock was released, False if runner_id is not the owner
    """
    current_raw = redis_client.get(MERGE_LOCK_KEY)
    if current_raw is None:
        logger.debug(f"[merge-lock] {runner_id} release 시도 — lock이 이미 없음")
        return False

    current = current_raw.decode() if isinstance(current_raw, bytes) else current_raw
    if current != runner_id:
        logger.warning(
            f"[merge-lock] {runner_id} release 거부 — 현재 소유자: {current}"
        )
        return False

    redis_client.delete(MERGE_LOCK_KEY)
    logger.info(f"[merge-lock] {runner_id} lock 해제 완료")
    return True


def get_merge_wait_queue(redis_client) -> list[str]:
    """
    현재 merge lock 대기 중인 runner ID 목록을 FIFO 순서로 반환한다.

    Args:
        redis_client: Redis 클라이언트 인스턴스

    Returns:
        list[str] — 대기 순서대로 정렬된 runner_id 목록 (비어 있으면 [])
    """
    raw_list = redis_client.lrange(MERGE_WAIT_QUEUE_KEY, 0, -1)
    return [item.decode() if isinstance(item, bytes) else item for item in raw_list]
