"""
TC: merge lock per-repo 통합 TC (실물 Redis DB15)

Phase T3 재현/통합 TC:
- test_concurrent_v2_merge_serialized_R: v2 동시 merge 직렬화 (RIGHT)
- test_subprocess_death_lock_release_R: subprocess 사망 시 cleanup → lock 해제 (RIGHT)
- test_concurrent_v1_v2_merge_serialized_R: v1/v2 혼합 동시 merge 직렬화 (RIGHT)
"""
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import redis

SCRIPTS_DIR = Path(__file__).parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from merge_lock import (
    acquire_merge_lock,
    release_merge_lock,
    get_merge_lock_key,
    get_merge_wait_queue_key,
    _get_repo_id,
)

REDIS_DB = 15
TEST_REPO_ID = "test-repo-integration"


@pytest.fixture
def r():
    client = redis.Redis(host="localhost", port=6379, db=REDIS_DB, decode_responses=True)
    for key in client.scan_iter(f"plan-runner:merge-lock:{TEST_REPO_ID}*"):
        client.delete(key)
    for key in client.scan_iter(f"plan-runner:merge-wait-queue:{TEST_REPO_ID}*"):
        client.delete(key)
    for key in client.scan_iter("plan-runner:merge-lock"):
        client.delete(key)
    for key in client.scan_iter("plan-runner:merge-wait-queue"):
        client.delete(key)
    yield client
    for key in client.scan_iter(f"plan-runner:merge-lock:{TEST_REPO_ID}*"):
        client.delete(key)
    for key in client.scan_iter(f"plan-runner:merge-wait-queue:{TEST_REPO_ID}*"):
        client.delete(key)


def test_concurrent_v2_merge_serialized_R(r):
    """R(Right): 실물 Redis + thread 2개 + 동일 repo_id → 순차 실행 (race condition 없음)

    thread_a: acquire → sleep(0.5) → release
    thread_b: acquire(timeout=5) → thread_a release 후 성공
    실행 순서: a_acquired, a_released, b_acquired
    """
    results = []
    lock_held = threading.Event()

    def thread_a():
        ok = acquire_merge_lock(r, "v2-runner-a", repo_id=TEST_REPO_ID, timeout=5, lock_ttl=10)
        results.append(("a_acquired", ok))
        lock_held.set()
        time.sleep(0.5)
        release_merge_lock(r, "v2-runner-a", repo_id=TEST_REPO_ID)
        results.append(("a_released",))

    def thread_b():
        lock_held.wait(timeout=3)
        ok = acquire_merge_lock(r, "v2-runner-b", repo_id=TEST_REPO_ID, timeout=5, lock_ttl=10)
        results.append(("b_acquired", ok))

    ta = threading.Thread(target=thread_a)
    tb = threading.Thread(target=thread_b)
    ta.start()
    tb.start()
    ta.join(timeout=8)
    tb.join(timeout=8)

    assert ("a_acquired", True) in results
    assert ("b_acquired", True) in results
    a_rel = next(i for i, x in enumerate(results) if x == ("a_released",))
    b_acq = next(i for i, x in enumerate(results) if x[0] == "b_acquired")
    assert a_rel < b_acq, f"b가 a_release 전에 lock 획득: {results}"


def test_subprocess_death_lock_release_R(r):
    """R(Right): lock 보유 → _cleanup_process_state 호출 → lock 즉시 해제 → 다른 runner acquire 성공"""
    import types

    # runner1이 lock 획득
    ok = acquire_merge_lock(r, "dying-runner", repo_id=TEST_REPO_ID, timeout=3, lock_ttl=30)
    assert ok is True
    assert r.get(get_merge_lock_key(TEST_REPO_ID)) == "dying-runner"

    # _dr_process_utils._cleanup_process_state 호출 (runner 사망 시뮬레이션)
    _mock_noise = types.ModuleType("listener_noise_filter")
    _mock_noise.NOISE_BLOCK_MARKERS = []
    _mock_noise.is_noise_line = lambda line: False
    sys.modules["listener_noise_filter"] = _mock_noise

    # PROJECT_ROOT를 test용으로 패치
    with patch("_dr_constants.PROJECT_ROOT", Path("D:/test/repo")), \
         patch("merge_lock._get_repo_id", return_value=TEST_REPO_ID), \
         patch("merge_lock.get_merge_wait_queue_key", return_value=get_merge_wait_queue_key(TEST_REPO_ID)):
        import _dr_process_utils
        import importlib
        importlib.reload(_dr_process_utils)
        _dr_process_utils._cleanup_process_state("dying-runner", r, reason="process_exit")

    # lock이 해제되어야 함
    assert r.get(get_merge_lock_key(TEST_REPO_ID)) is None

    # 다른 runner가 즉시 acquire 가능
    ok2 = acquire_merge_lock(r, "next-runner", repo_id=TEST_REPO_ID, timeout=3, lock_ttl=10)
    assert ok2 is True
    release_merge_lock(r, "next-runner", repo_id=TEST_REPO_ID)


def test_concurrent_v1_v2_merge_serialized_R(r):
    """R(Right): v1 패턴(acquire_merge_lock) + v2 인라인 lock → 동일 Redis 키로 직렬화

    v1: acquire_merge_lock(repo_id=TEST_REPO_ID)
    v2: _ml_acquire (merge_stage.py 인라인 헬퍼)
    같은 plan-runner:merge-lock:{repo_id} 키를 공유하므로 직렬화되어야 함
    """
    # wtools plan-runner 경로 추가
    wtools_core = Path(__file__).parents[4] / "service" / "wtools" / "common" / "tools" / "plan-runner"
    if str(wtools_core) not in sys.path:
        sys.path.insert(0, str(wtools_core))

    from plan_runner.core.merge_stage import _ml_acquire, _ml_release

    results = []
    v1_held = threading.Event()

    def thread_v1():
        ok = acquire_merge_lock(r, "v1-runner", repo_id=TEST_REPO_ID, timeout=5, lock_ttl=10)
        results.append(("v1_acquired", ok))
        v1_held.set()
        time.sleep(0.5)
        release_merge_lock(r, "v1-runner", repo_id=TEST_REPO_ID)
        results.append(("v1_released",))

    def thread_v2():
        v1_held.wait(timeout=3)
        ok = _ml_acquire(r, "v2-runner", TEST_REPO_ID, timeout=5)
        results.append(("v2_acquired", ok))
        if ok:
            _ml_release(r, "v2-runner", TEST_REPO_ID)

    tv1 = threading.Thread(target=thread_v1)
    tv2 = threading.Thread(target=thread_v2)
    tv1.start()
    tv2.start()
    tv1.join(timeout=8)
    tv2.join(timeout=8)

    assert ("v1_acquired", True) in results
    assert ("v2_acquired", True) in results
    v1_rel = next(i for i, x in enumerate(results) if x == ("v1_released",))
    v2_acq = next(i for i, x in enumerate(results) if x[0] == "v2_acquired")
    assert v1_rel < v2_acq, f"v2가 v1_release 전에 lock 획득: {results}"
