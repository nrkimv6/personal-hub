"""
Merge Lock 유틸리티 — Redis 기반 분산 lock (SETNX + FIFO 대기 큐)

Redis 키 구조:
  plan-runner:merge-lock                  → lock 보유 runner_id (글로벌, 하위 호환)
  plan-runner:merge-lock:{repo_id}        → lock 보유 runner_id (per-repo)
  plan-runner:merge-wait-queue            → 대기 중인 runner_id 목록 (글로벌, 하위 호환)
  plan-runner:merge-wait-queue:{repo_id} → 대기 중인 runner_id 목록 (per-repo)
"""

import os
import time
import logging
from pathlib import Path

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


def _get_repo_id(project_root: Path) -> str:
    """프로젝트 루트 경로를 Redis 키 안전 문자열로 정규화한다.

    Windows 경로 변형(백슬래시/슬래시, 대소문자)을 모두 동일 값으로 매핑한다.
    예: D:\\work\\project\\tools\\monitor-page → d:-work-project-tools-monitor-page

    Args:
        project_root: 프로젝트 루트 Path 객체

    Returns:
        str — Redis 키에 안전하게 사용할 수 있는 소문자 하이픈 구분 문자열
    """
    return str(project_root.resolve()).replace("\\", "/").lower().strip("/").replace("/", "-")


def get_merge_lock_key(repo_id: str = None) -> str:
    """per-repo 또는 글로벌 merge lock Redis 키를 반환한다.

    Args:
        repo_id: _get_repo_id()로 생성한 레포 식별자. None이면 글로벌 키 반환 (하위 호환).

    Returns:
        str — Redis lock 키
    """
    if repo_id is None:
        return MERGE_LOCK_KEY
    return f"plan-runner:merge-lock:{repo_id}"


def get_merge_wait_queue_key(repo_id: str = None) -> str:
    """per-repo 또는 글로벌 merge wait queue Redis 키를 반환한다.

    Args:
        repo_id: _get_repo_id()로 생성한 레포 식별자. None이면 글로벌 키 반환 (하위 호환).

    Returns:
        str — Redis wait queue 키
    """
    if repo_id is None:
        return MERGE_WAIT_QUEUE_KEY
    return f"plan-runner:merge-wait-queue:{repo_id}"


def acquire_merge_lock(redis_client, runner_id: str, repo_id: str = None, timeout: int = 600, lock_ttl: int = None) -> bool:
    """
    Merge lock을 획득한다 (SETNX + FIFO 대기 큐 조합).

    1. 대기 큐에 runner_id를 RPUSH (이미 있으면 스킵)
    2. 폴링: lock이 없거나 내 차례(큐 맨 앞)이면 SETNX 시도
    3. 성공 시 큐에서 제거 후 True 반환
    4. timeout 초 내 획득 실패 시 큐에서 제거 후 False 반환

    Args:
        redis_client: Redis 클라이언트 인스턴스
        runner_id: 현재 runner의 고유 ID (문자열)
        repo_id: _get_repo_id()로 생성한 레포 식별자. None이면 글로벌 키 사용 (하위 호환).
        timeout: 최대 대기 시간 (초, 기본 600)
        lock_ttl: lock TTL (초, 기본 MERGE_LOCK_TTL=600). 테스트 시 짧게 지정 가능.

    Returns:
        True if lock acquired, False if timed out
    """
    _ttl = lock_ttl if lock_ttl is not None else MERGE_LOCK_TTL
    _lock_key = get_merge_lock_key(repo_id)
    _queue_key = get_merge_wait_queue_key(repo_id)

    # 대기 큐에 원자적 등록 (Lua: 중복 방지 + RPUSH)
    enqueued = redis_client.eval(_ENQUEUE_LUA, 1, _queue_key, runner_id)
    if enqueued == 1:
        logger.info(f"[merge-lock] {runner_id} 대기 큐 등록")
    # 큐 LIST 자체에 TTL 설정 (비정상 종료 후 큐 잔류 방지, 활성 runner가 있는 한 갱신됨)
    redis_client.expire(_queue_key, MERGE_LOCK_TTL * 2)

    deadline = time.time() + timeout
    poll_interval = 1.0  # seconds

    while time.time() < deadline:
        # 큐 맨 앞이 나인지 확인
        front_raw = redis_client.lindex(_queue_key, 0)
        front = front_raw.decode() if isinstance(front_raw, bytes) else front_raw

        if front == runner_id:
            # 내 차례 — lock 획득 시도
            acquired = redis_client.set(_lock_key, runner_id, nx=True, ex=_ttl)
            if acquired:
                # 큐에서 제거
                redis_client.lrem(_queue_key, 1, runner_id)
                logger.info(f"[merge-lock] {runner_id} lock 획득 완료")
                return True
        elif front is not None and front != runner_id:
            # 큐 맨 앞이 다른 runner — stale 여부 확인
            _remove_if_stale(redis_client, front, repo_id)

        time.sleep(poll_interval)

    # timeout — 큐에서 제거
    redis_client.lrem(_queue_key, 1, runner_id)
    logger.warning(f"[merge-lock] {runner_id} lock 획득 timeout ({timeout}s)")
    return False


def _remove_if_stale(redis_client, front: str, repo_id: str = None) -> bool:
    """큐 맨 앞 runner가 죽었으면 대기 큐에서 제거한다.

    PID Redis 키 → os.kill(0) 생존 확인 → 죽었으면 LREM.
    PID 키가 없는 경우 status 키로 판단.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        front: 큐 맨 앞 runner_id
        repo_id: per-repo 큐 키 사용 시 레포 식별자. None이면 글로벌 키.

    Returns:
        True if removed (stale), False if alive or indeterminate
    """
    _queue_key = get_merge_wait_queue_key(repo_id)
    pid_raw = redis_client.get(f"{_RUNNER_KEY_PREFIX}:{front}:pid")
    if pid_raw is not None:
        try:
            pid = int(pid_raw.decode() if isinstance(pid_raw, bytes) else pid_raw)
            os.kill(pid, 0)  # 생존 확인 (signal 0, 실제 시그널 미전송)
            return False  # 살아있음
        except (ProcessLookupError, OSError):
            # 죽은 프로세스
            redis_client.lrem(_queue_key, 1, front)
            logger.warning(f"[merge-lock] stale front runner 제거 (pid 없음): {front}")
            return True
        except (ValueError, TypeError):
            pass  # pid 파싱 실패 → status 기반 판단으로 fall-through

    # PID 키 없음 또는 파싱 실패 → status 키로 판단
    status_raw = redis_client.get(f"{_RUNNER_KEY_PREFIX}:{front}:status")
    status = status_raw.decode() if isinstance(status_raw, bytes) else status_raw
    if status in (None, "stopped", "error", "failed"):
        redis_client.lrem(_queue_key, 1, front)
        logger.warning(f"[merge-lock] stale front runner 제거 (status={status}): {front}")
        return True

    return False  # status="running" 등, 살아있는 것으로 간주


def release_merge_lock(redis_client, runner_id: str, repo_id: str = None) -> bool:
    """
    Merge lock을 해제한다 (Lua 원자 스크립트로 소유자 확인 + DEL).

    GET+비교+DELETE를 단일 Lua eval로 실행하여 race condition 방지.
    소유자 불일치 또는 이미 만료된 경우 False를 반환하고 아무 것도 하지 않는다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        runner_id: 현재 runner의 고유 ID (문자열)
        repo_id: _get_repo_id()로 생성한 레포 식별자. None이면 글로벌 키 사용 (하위 호환).

    Returns:
        True if lock was released, False if runner_id is not the owner
    """
    _lock_key = get_merge_lock_key(repo_id)
    result = redis_client.eval(_RELEASE_LUA, 1, _lock_key, runner_id)
    if result == 1:
        logger.info(f"[merge-lock] {runner_id} lock 해제 완료")
        return True
    else:
        logger.debug(f"[merge-lock] {runner_id} release 거부 — 소유자 불일치 또는 이미 만료")
        return False


def get_merge_wait_queue(redis_client, repo_id: str = None) -> list:
    """
    현재 merge lock 대기 중인 runner ID 목록을 FIFO 순서로 반환한다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        repo_id: _get_repo_id()로 생성한 레포 식별자. None이면 글로벌 키 사용 (하위 호환).

    Returns:
        list[str] — 대기 순서대로 정렬된 runner_id 목록 (비어 있으면 [])
    """
    _queue_key = get_merge_wait_queue_key(repo_id)
    raw_list = redis_client.lrange(_queue_key, 0, -1)
    return [item.decode() if isinstance(item, bytes) else item for item in raw_list]
