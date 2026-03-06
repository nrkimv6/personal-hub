"""
Merge Lock 유틸리티 — Redis 기반 분산 lock (SETNX + FIFO 대기 큐)

Redis 키 구조:
  plan-runner:merge-lock          → lock 보유 runner_id (STRING, TTL 600초)
  plan-runner:merge-wait-queue    → 대기 중인 runner_id 목록 (LIST, FIFO)
"""

import os
import time
import logging

logger = logging.getLogger(__name__)

MERGE_LOCK_KEY = "plan-runner:merge-lock"
MERGE_WAIT_QUEUE_KEY = "plan-runner:merge-wait-queue"
MERGE_LOCK_TTL = 600  # seconds

# runner Redis 키 prefix (stale front 감지 시 PID/status 확인용)
_RUNNER_KEY_PREFIX = "plan-runner:runners"

# Lua 스크립트: GET+비교+DELETE 원자화 (race condition 방지)
# 반환값: 1=해제 성공, 0=소유자 불일치 또는 lock 없음
_RELEASE_LUA = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] "
    "then return redis.call('DEL', KEYS[1]) "
    "else return 0 end"
)

# Lua 스크립트: LRANGE+중복확인+RPUSH 원자화
# 반환값: 1=새로 등록, 0=이미 존재(스킵)
_ENQUEUE_LUA = (
    "local items = redis.call('LRANGE', KEYS[1], 0, -1); "
    "for i=1,#items do "
    "  if items[i] == ARGV[1] then return 0 end "
    "end; "
    "redis.call('RPUSH', KEYS[1], ARGV[1]); "
    "return 1"
)


def acquire_merge_lock(redis_client, runner_id: str, timeout: int = 600, lock_ttl: int = None) -> bool:
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
        lock_ttl: lock TTL (초, 기본 MERGE_LOCK_TTL=600). 테스트 시 짧게 지정 가능.

    Returns:
        True if lock acquired, False if timed out
    """
    _ttl = lock_ttl if lock_ttl is not None else MERGE_LOCK_TTL
    # 대기 큐에 원자적 등록 (Lua: 중복 방지 + RPUSH)
    enqueued = redis_client.eval(_ENQUEUE_LUA, 1, MERGE_WAIT_QUEUE_KEY, runner_id)
    if enqueued == 1:
        logger.info(f"[merge-lock] {runner_id} 대기 큐 등록")
    # 큐 LIST 자체에 TTL 설정 (비정상 종료 후 큐 잔류 방지, 활성 runner가 있는 한 갱신됨)
    redis_client.expire(MERGE_WAIT_QUEUE_KEY, MERGE_LOCK_TTL * 2)

    deadline = time.time() + timeout
    poll_interval = 1.0  # seconds

    while time.time() < deadline:
        # 큐 맨 앞이 나인지 확인
        front_raw = redis_client.lindex(MERGE_WAIT_QUEUE_KEY, 0)
        front = front_raw.decode() if isinstance(front_raw, bytes) else front_raw

        if front == runner_id:
            # 내 차례 — lock 획득 시도
            acquired = redis_client.set(MERGE_LOCK_KEY, runner_id, nx=True, ex=_ttl)
            if acquired:
                # 큐에서 제거
                redis_client.lrem(MERGE_WAIT_QUEUE_KEY, 1, runner_id)
                logger.info(f"[merge-lock] {runner_id} lock 획득 완료")
                return True
        elif front is not None and front != runner_id:
            # 큐 맨 앞이 다른 runner — stale 여부 확인
            _remove_if_stale(redis_client, front)

        time.sleep(poll_interval)

    # timeout — 큐에서 제거
    redis_client.lrem(MERGE_WAIT_QUEUE_KEY, 1, runner_id)
    logger.warning(f"[merge-lock] {runner_id} lock 획득 timeout ({timeout}s)")
    return False


def _remove_if_stale(redis_client, front: str) -> bool:
    """큐 맨 앞 runner가 죽었으면 대기 큐에서 제거한다.

    PID Redis 키 → os.kill(0) 생존 확인 → 죽었으면 LREM.
    PID 키가 없는 경우 status 키로 판단.

    Returns:
        True if removed (stale), False if alive or indeterminate
    """
    pid_raw = redis_client.get(f"{_RUNNER_KEY_PREFIX}:{front}:pid")
    if pid_raw is not None:
        try:
            pid = int(pid_raw.decode() if isinstance(pid_raw, bytes) else pid_raw)
            os.kill(pid, 0)  # 생존 확인 (signal 0, 실제 시그널 미전송)
            return False  # 살아있음
        except (ProcessLookupError, OSError):
            # 죽은 프로세스
            redis_client.lrem(MERGE_WAIT_QUEUE_KEY, 1, front)
            logger.warning(f"[merge-lock] stale front runner 제거 (pid 없음): {front}")
            return True
        except (ValueError, TypeError):
            pass  # pid 파싱 실패 → status 기반 판단으로 fall-through

    # PID 키 없음 또는 파싱 실패 → status 키로 판단
    status_raw = redis_client.get(f"{_RUNNER_KEY_PREFIX}:{front}:status")
    status = status_raw.decode() if isinstance(status_raw, bytes) else status_raw
    if status in (None, "stopped", "error", "failed"):
        redis_client.lrem(MERGE_WAIT_QUEUE_KEY, 1, front)
        logger.warning(f"[merge-lock] stale front runner 제거 (status={status}): {front}")
        return True

    return False  # status="running" 등, 살아있는 것으로 간주


def release_merge_lock(redis_client, runner_id: str) -> bool:
    """
    Merge lock을 해제한다 (Lua 원자 스크립트로 소유자 확인 + DEL).

    GET+비교+DELETE를 단일 Lua eval로 실행하여 race condition 방지.
    소유자 불일치 또는 이미 만료된 경우 False를 반환하고 아무 것도 하지 않는다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        runner_id: 현재 runner의 고유 ID (문자열)

    Returns:
        True if lock was released, False if runner_id is not the owner
    """
    result = redis_client.eval(_RELEASE_LUA, 1, MERGE_LOCK_KEY, runner_id)
    if result == 1:
        logger.info(f"[merge-lock] {runner_id} lock 해제 완료")
        return True
    else:
        logger.debug(f"[merge-lock] {runner_id} release 거부 — 소유자 불일치 또는 이미 만료")
        return False


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
