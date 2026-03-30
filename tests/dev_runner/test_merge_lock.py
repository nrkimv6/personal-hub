"""
merge_lock.py 유닛 테스트

T1 TC:
- test_merge_lock_acquire_release: lock 획득/해제 정상 동작 (RIGHT)
- test_merge_lock_fifo_ordering: 2개 runner 순차 lock 획득 (BOUNDARY)
- test_merge_lock_ttl_recovery: TTL 만료 시 다음 runner 획득 (ERROR)
"""
import sys
import time
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import redis

# scripts/ 디렉토리를 sys.path에 추가
SCRIPTS_DIR = Path(__file__).parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from merge_lock import acquire_merge_lock, release_merge_lock, get_merge_wait_queue

pytestmark = pytest.mark.skip(reason="merge_lock deprecated — merge_queue로 대체")

REDIS_DB = 15  # 테스트 전용 DB


@pytest.fixture
def redis_client():
    """테스트 전용 Redis DB (DB15) 사용 — 완료 후 정리"""
    r = redis.Redis(host="localhost", port=6379, db=REDIS_DB, decode_responses=True)
    # 테스트 시작 전 관련 키 정리
    for key in r.scan_iter("plan-runner:merge-lock*"):
        r.delete(key)
    for key in r.scan_iter("plan-runner:merge-wait-queue*"):
        r.delete(key)
    yield r
    # 테스트 후 정리
    for key in r.scan_iter("plan-runner:merge-lock*"):
        r.delete(key)
    for key in r.scan_iter("plan-runner:merge-wait-queue*"):
        r.delete(key)


def test_merge_lock_acquire_release(redis_client):
    """lock 획득/해제 정상 동작 (RIGHT)

    - acquire 성공 → True 반환
    - release 후 lock 키 삭제 확인
    - 재획득 가능 확인
    """
    runner_id = "t-mlock-001"

    # 1. lock 획득
    acquired = acquire_merge_lock(redis_client, runner_id, timeout=10)
    assert acquired is True, "첫 번째 lock 획득이 실패하면 안 됨"

    # lock 키가 존재하는지 확인
    lock_val = redis_client.get("plan-runner:merge-lock")
    assert lock_val == runner_id, f"lock 소유자가 '{runner_id}'여야 함, 실제: {lock_val}"

    # 2. lock 해제
    release_merge_lock(redis_client, runner_id)
    lock_val_after = redis_client.get("plan-runner:merge-lock")
    assert lock_val_after is None, "release 후 lock 키가 삭제되어야 함"

    # 3. 재획득 가능 확인
    re_acquired = acquire_merge_lock(redis_client, runner_id, timeout=5)
    assert re_acquired is True, "release 후 재획득이 가능해야 함"
    release_merge_lock(redis_client, runner_id)


def test_merge_lock_fifo_ordering(redis_client):
    """2개 runner 순차 lock 획득 (BOUNDARY)

    - runner A가 먼저 대기 큐에 진입 → A가 먼저 lock 획득
    - runner B는 A 완료 후 획득
    """
    runner_a = "test-runner-A"
    runner_b = "test-runner-B"

    results: list[str] = []
    lock_event = threading.Event()

    def run_a():
        acquired = acquire_merge_lock(redis_client, runner_a, timeout=15)
        if acquired:
            results.append(runner_a)
            lock_event.set()
            time.sleep(0.3)  # B가 대기하도록 잠시 보유
            release_merge_lock(redis_client, runner_a)

    def run_b():
        # A가 lock을 먼저 잡을 때까지 잠시 대기
        lock_event.wait(timeout=5)
        acquired = acquire_merge_lock(redis_client, runner_b, timeout=15)
        if acquired:
            results.append(runner_b)
            release_merge_lock(redis_client, runner_b)

    t_a = threading.Thread(target=run_a)
    t_b = threading.Thread(target=run_b)

    t_a.start()
    time.sleep(0.05)  # A가 먼저 시작
    t_b.start()

    t_a.join(timeout=10)
    t_b.join(timeout=10)

    assert results == [runner_a, runner_b], (
        f"FIFO 순서여야 함: [A, B], 실제: {results}"
    )


def test_merge_lock_ttl_recovery(redis_client):
    """TTL 만료 시 다음 runner 획득 (ERROR)

    - lock을 획득한 runner가 release 없이 TTL 만료
    - TTL 만료 후 다음 runner가 lock 획득 가능
    """
    runner_stale = "test-runner-stale"
    runner_next = "test-runner-next"

    # 1. stale runner가 TTL=1초로 lock 획득
    acquired = acquire_merge_lock(redis_client, runner_stale, timeout=5, lock_ttl=1)
    assert acquired is True, "stale runner lock 획득 실패"

    # stale runner가 release 없이 종료 (TTL 만료 대기)
    time.sleep(1.5)

    # 2. lock 키가 만료되었는지 확인
    lock_val = redis_client.get("plan-runner:merge-lock")
    assert lock_val is None, f"TTL 만료 후 lock 키가 남아있으면 안 됨, 실제: {lock_val}"

    # 3. 다음 runner가 lock 획득 가능
    next_acquired = acquire_merge_lock(redis_client, runner_next, timeout=5)
    assert next_acquired is True, "TTL 만료 후 다음 runner가 lock을 획득할 수 있어야 함"
    release_merge_lock(redis_client, runner_next)
