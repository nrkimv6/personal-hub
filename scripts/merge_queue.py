"""
Merge Queue 유틸리티 — Redis LIST 큐 + BRPOP 시그널 기반 동시 머지 순차화

merge_lock.py(SETNX+폴링)의 드롭인 교체. 러너 자체가 merge 실행 주체이며,
순서 대기만 큐+시그널로 교체한다.

Redis 키 구조:
  plan-runner:merge-queue:{repo_id}   → runner_id LIST (index 0=실행 중, 1+=대기)
  plan-runner:merge-turn:{runner_id}  → BRPOP 대기용 signal 키 (값="go")
"""

import os
import time
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

MERGE_QUEUE_KEY = "plan-runner:merge-queue"
MERGE_TURN_KEY_PREFIX = "plan-runner:merge-turn"
_RUNNER_KEY_PREFIX = "plan-runner:runners"  # PID/status 조회용, merge_lock과 동일

# Lua 스크립트: LRANGE 순회 → 중복 없으면 RPUSH, 있으면 skip (원자적 중복 방지 enqueue)
# merge_lock._ENQUEUE_LUA 동일 패턴
_ENQUEUE_LUA = (
    "local items = redis.call('LRANGE', KEYS[1], 0, -1); "
    "for i=1,#items do "
    "  if items[i] == ARGV[1] then return 0 end "
    "end; "
    "redis.call('RPUSH', KEYS[1], ARGV[1]); "
    "return 1"
)


def _is_pid_alive(pid: int) -> bool:
    """PID 생존 여부를 안전하게 확인한다.

    Windows에서 ``os.kill(pid, 0)``는 POSIX와 달리 안전한 존재 확인이 아니므로
    우선 ``psutil.pid_exists``를 사용한다.
    """
    if pid <= 0:
        return False

    if sys.platform == "win32":
        try:
            import psutil

            return bool(psutil.pid_exists(pid))
        except Exception:
            # psutil 사용 불가 시 OpenProcess fallback
            try:
                import ctypes

                SYNCHRONIZE = 0x00100000
                handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
                if handle == 0:
                    return False
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            except Exception:
                return False

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


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


def get_queue_key(repo_id: str) -> str:
    """per-repo merge queue Redis 키를 반환한다.

    Args:
        repo_id: _get_repo_id()로 생성한 레포 식별자

    Returns:
        str — Redis merge queue 키
    """
    return f"{MERGE_QUEUE_KEY}:{repo_id}"


def get_turn_key(runner_id: str) -> str:
    """BRPOP 대기용 signal Redis 키를 반환한다.

    Args:
        runner_id: 대기 중인 runner의 고유 ID

    Returns:
        str — Redis merge-turn signal 키
    """
    return f"{MERGE_TURN_KEY_PREFIX}:{runner_id}"


def _remove_if_stale(redis_client, front: str, repo_id: str) -> bool:
    """큐 맨 앞 runner가 죽었으면 큐에서 제거하고 다음 runner에게 signal을 보낸다.

    PID Redis 키 → 안전한 PID 생존 확인 → 죽었으면 LREM.
    LREM 후 새 front runner에게 LPUSH signal.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        front: 큐 맨 앞 runner_id
        repo_id: per-repo 큐 키용 레포 식별자

    Returns:
        True if removed (stale), False if alive or indeterminate
    """
    _queue_key = get_queue_key(repo_id)
    pid_raw = redis_client.get(f"{_RUNNER_KEY_PREFIX}:{front}:pid")
    if pid_raw is not None:
        try:
            pid = int(pid_raw.decode() if isinstance(pid_raw, bytes) else pid_raw)
            if _is_pid_alive(pid):
                return False
        except (ValueError, TypeError):
            pass  # pid 파싱 실패 → status 기반 판단으로 fall-through

    # PID 없거나 죽었음 → status 키로 추가 판단
    if pid_raw is not None:
        # PID가 있었는데 죽었으므로 바로 stale 처리
        redis_client.lrem(_queue_key, 1, front)
        logger.warning(f"[merge-queue] stale front runner 제거 (pid dead): {front}")
        _signal_next(redis_client, _queue_key)
        return True

    # PID 키 없음 → status 키로 판단
    status_raw = redis_client.get(f"{_RUNNER_KEY_PREFIX}:{front}:status")
    status = status_raw.decode() if isinstance(status_raw, bytes) else status_raw
    if status in (None, "stopped", "error", "failed"):
        redis_client.lrem(_queue_key, 1, front)
        logger.warning(f"[merge-queue] stale front runner 제거 (status={status}): {front}")
        _signal_next(redis_client, _queue_key)
        return True

    return False  # status="running" 등, 살아있는 것으로 간주


def _signal_next(redis_client, queue_key: str) -> None:
    """큐의 현재 front runner에게 BRPOP signal을 전송한다."""
    next_raw = redis_client.lindex(queue_key, 0)
    if next_raw is not None:
        next_runner = next_raw.decode() if isinstance(next_raw, bytes) else next_raw
        turn_key = get_turn_key(next_runner)
        redis_client.lpush(turn_key, "go")
        redis_client.expire(turn_key, 600)


def acquire_merge_turn(
    redis_client,
    runner_id: str,
    repo_id: str = None,
    timeout: int = 600,
    queue_ttl: int = 1200,
) -> bool:
    """
    Merge turn을 획득한다 (Redis LIST 큐 + BRPOP 시그널).

    1. DEL turn_key (stale signal 정리)
    2. _ENQUEUE_LUA로 원자적 중복방지 enqueue + EXPIRE queue_key
    3. LINDEX 0 == me? → YES: 즉시 True 반환 (첫 진입자)
    4. NO: BRPOP merge-turn:{runner_id} 블로킹 대기 (5초 단위 루프)
       - 수신 시 LINDEX 0 == me 재확인 → True (spurious signal 방어)
       - 매 5초 timeout 시: 큐 소멸 감지(→ False), stale front 감지(→ 자동 승격)
    5. 전체 timeout 시: LREM self + False

    Args:
        redis_client: Redis 클라이언트 인스턴스
        runner_id: 현재 runner의 고유 ID (문자열)
        repo_id: _get_repo_id()로 생성한 레포 식별자. None이면 _get_repo_id(Path.cwd()) 자동 호출.
        timeout: 최대 대기 시간 (초, 기본 600)
        queue_ttl: merge queue 키 TTL (초, 기본 1200). 테스트 시 짧게 지정 가능.

    Returns:
        True if turn acquired, False if timed out or queue expired
    """
    if repo_id is None:
        repo_id = _get_repo_id(Path.cwd())

    _queue_key = get_queue_key(repo_id)
    _turn_key = get_turn_key(runner_id)

    try:
        # stale signal 정리 (이전 세션 잔존 방어)
        redis_client.delete(_turn_key)

        # 원자적 중복방지 enqueue
        redis_client.eval(_ENQUEUE_LUA, 1, _queue_key, runner_id)
        redis_client.expire(_queue_key, queue_ttl)
        logger.info(f"[merge-queue] {runner_id} 큐 등록")

        # 즉시 확인: 내가 front면 바로 실행
        front_raw = redis_client.lindex(_queue_key, 0)
        front = front_raw.decode() if isinstance(front_raw, bytes) else front_raw
        if front == runner_id:
            logger.info(f"[merge-queue] {runner_id} turn 즉시 획득 (front)")
            return True

        # 대기: BRPOP 루프 (5초 단위)
        deadline = time.time() + timeout
        brpop_timeout = 5  # 초

        while time.time() < deadline:
            result = redis_client.brpop(_turn_key, timeout=brpop_timeout)

            if result is not None:
                # signal 수신 — LINDEX 0 == me 재확인 (spurious signal 방어)
                check_raw = redis_client.lindex(_queue_key, 0)
                check = check_raw.decode() if isinstance(check_raw, bytes) else check_raw
                if check == runner_id:
                    logger.info(f"[merge-queue] {runner_id} turn 획득 (signal)")
                    return True
                # spurious signal — loop back
                continue

            # BRPOP timeout (5초) — 상태 점검
            front_raw = redis_client.lindex(_queue_key, 0)
            if front_raw is None:
                # 큐 소멸 (EXPIRE/FLUSHDB)
                logger.warning(f"[merge-queue] {runner_id} 큐 소멸 감지 → False 반환")
                return False

            front = front_raw.decode() if isinstance(front_raw, bytes) else front_raw

            # stale front 감지 및 제거
            if front != runner_id:
                _remove_if_stale(redis_client, front, repo_id)
                # 제거 후 내가 front가 됐으면 즉시 True
                new_front_raw = redis_client.lindex(_queue_key, 0)
                new_front = new_front_raw.decode() if isinstance(new_front_raw, bytes) else new_front_raw
                if new_front == runner_id:
                    logger.info(f"[merge-queue] {runner_id} turn 획득 (stale 제거 후 승격)")
                    return True

        # 전체 timeout
        redis_client.lrem(_queue_key, 1, runner_id)
        logger.warning(f"[merge-queue] {runner_id} turn 획득 timeout ({timeout}s)")
        return False

    except Exception:
        # 예외 시 self-cleanup 후 re-raise
        try:
            redis_client.lrem(_queue_key, 1, runner_id)
        except Exception:
            pass
        raise


def release_merge_turn(redis_client, runner_id: str, repo_id: str = None) -> bool:
    """
    Merge turn을 해제한다 (LREM self + 다음 runner에게 signal).

    1. LREM queue_key 1 runner_id
    2. removed > 0이면: LINDEX 0으로 next runner 확인 → LPUSH signal + EXPIRE
    3. 큐에 대기자가 남아있으면 queue_key TTL 갱신
    4. return removed > 0

    Args:
        redis_client: Redis 클라이언트 인스턴스
        runner_id: 현재 runner의 고유 ID (문자열)
        repo_id: _get_repo_id()로 생성한 레포 식별자. None이면 _get_repo_id(Path.cwd()) 자동 호출.

    Returns:
        True if successfully removed (was in queue), False if already absent
    """
    if repo_id is None:
        repo_id = _get_repo_id(Path.cwd())

    _queue_key = get_queue_key(repo_id)
    removed = redis_client.lrem(_queue_key, 1, runner_id)

    if removed > 0:
        next_raw = redis_client.lindex(_queue_key, 0)
        if next_raw is not None:
            next_runner = next_raw.decode() if isinstance(next_raw, bytes) else next_raw
            turn_key = get_turn_key(next_runner)
            redis_client.lpush(turn_key, "go")
            redis_client.expire(turn_key, 600)
            redis_client.expire(_queue_key, 1200)  # 대기자 남아있을 때 TTL 갱신
            logger.info(f"[merge-queue] {runner_id} release → {next_runner} signal 전송")
        else:
            logger.info(f"[merge-queue] {runner_id} release 완료 (큐 비어있음)")
        return True
    else:
        logger.debug(f"[merge-queue] {runner_id} release — 큐에 없음 (이미 제거됨)")
        return False


def get_merge_queue(redis_client, repo_id: str = None) -> list:
    """
    현재 merge queue의 runner ID 목록을 FIFO 순서로 반환한다.

    index 0 = 현재 머지 실행 중인 runner, 1+ = 대기 runner.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        repo_id: _get_repo_id()로 생성한 레포 식별자. None이면 _get_repo_id(Path.cwd()) 자동 호출.

    Returns:
        list[str] — 큐 순서대로 정렬된 runner_id 목록 (비어 있으면 [])
    """
    if repo_id is None:
        repo_id = _get_repo_id(Path.cwd())

    _queue_key = get_queue_key(repo_id)
    raw_list = redis_client.lrange(_queue_key, 0, -1)
    return [item.decode() if isinstance(item, bytes) else item for item in raw_list]


def get_merge_queue_length(redis_client, repo_id: str = None) -> int:
    """
    현재 merge queue의 전체 길이를 반환한다 (실행 중 + 대기).

    주의: 이 함수는 LLEN 전체를 반환한다 (index 0 = 실행 중인 runner 포함).
    순수 대기 수만 필요하면 max(0, result - 1)을 사용할 것.

    executor_service.get_merge_queue_length()는 max(0, LLEN-1)을 반환하므로
    소비자별 의미가 다름에 주의.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        repo_id: _get_repo_id()로 생성한 레포 식별자. None이면 _get_repo_id(Path.cwd()) 자동 호출.

    Returns:
        int — 전체 큐 길이 (실행 중 + 대기, 큐 없으면 0)
    """
    if repo_id is None:
        repo_id = _get_repo_id(Path.cwd())

    _queue_key = get_queue_key(repo_id)
    return redis_client.llen(_queue_key)
