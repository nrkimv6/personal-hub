"""
merge_lock per-repo 기능 단위 테스트

Phase T1 TC:
- test_get_repo_id_normalization_R: Path → repo_id 정규화 확인 (RIGHT)
- test_get_repo_id_same_path_variants_B: 경로 변형 동일 결과 확인 (BOUNDARY)
- test_get_repo_id_different_paths_B: 다른 경로 → 다른 repo_id (BOUNDARY)
- test_acquire_release_per_repo_R: 다른 repo_id 독립 lock (RIGHT)
- test_acquire_same_repo_blocks_R: 같은 repo_id 직렬화 (RIGHT)
- test_backward_compat_no_repo_id_B: repo_id=None → 글로벌 키 (BOUNDARY)
- test_merge_lock_key_isolation_B: per-repo 큐 키 격리 (BOUNDARY)
"""
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

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

pytestmark = pytest.mark.skip(reason="merge_lock deprecated — merge_queue로 대체")

REDIS_DB = 15


@pytest.fixture
def redis_client():
    r = redis.Redis(host="localhost", port=6379, db=REDIS_DB, decode_responses=True)
    for key in r.scan_iter("plan-runner:merge-lock*"):
        r.delete(key)
    for key in r.scan_iter("plan-runner:merge-wait-queue*"):
        r.delete(key)
    yield r
    for key in r.scan_iter("plan-runner:merge-lock*"):
        r.delete(key)
    for key in r.scan_iter("plan-runner:merge-wait-queue*"):
        r.delete(key)


# ---------------------------------------------------------------------------
# _get_repo_id
# ---------------------------------------------------------------------------

def test_get_repo_id_normalization_R():
    """R(Right): Path('D:/work/project/tools/monitor-page') → 소문자 하이픈 구분 문자열"""
    result = _get_repo_id(Path("D:/work/project/tools/monitor-page"))
    assert result == "d:-work-project-tools-monitor-page"
    assert " " not in result
    assert "\\" not in result
    assert "/" not in result
    assert result == result.lower()


def test_get_repo_id_same_path_variants_B():
    """B(Boundary): 백슬래시/슬래시/대소문자 변형 → 동일 repo_id"""
    p1 = _get_repo_id(Path("D:\\work\\project"))
    p2 = _get_repo_id(Path("D:/work/project"))
    # Path로 변환 시 OS 정규화됨 — resolve() 없이도 비교
    assert p1 == p2


def test_get_repo_id_different_paths_B():
    """B(Boundary): 다른 경로 → 다른 repo_id"""
    id_a = _get_repo_id(Path("D:/repo-a"))
    id_b = _get_repo_id(Path("D:/repo-b"))
    assert id_a != id_b


# ---------------------------------------------------------------------------
# per-repo lock 독립성
# ---------------------------------------------------------------------------

def test_acquire_release_per_repo_R(redis_client):
    """R(Right): 다른 repo_id → lock이 서로 독립적으로 획득 가능"""
    acquired_a = acquire_merge_lock(redis_client, "runner1", repo_id="repo-a", timeout=3, lock_ttl=30)
    acquired_b = acquire_merge_lock(redis_client, "runner2", repo_id="repo-b", timeout=3, lock_ttl=30)
    assert acquired_a is True
    assert acquired_b is True
    # 키 구조 검증
    assert redis_client.get("plan-runner:merge-lock:repo-a") == "runner1"
    assert redis_client.get("plan-runner:merge-lock:repo-b") == "runner2"
    release_merge_lock(redis_client, "runner1", repo_id="repo-a")
    release_merge_lock(redis_client, "runner2", repo_id="repo-b")


def test_acquire_same_repo_blocks_R(redis_client):
    """R(Right): 같은 repo_id, 다른 runner → 직렬화 (두 번째 acquire는 첫 번째 release 후 성공)"""
    results = []
    lock_held = threading.Event()
    lock_released = threading.Event()

    def thread_a():
        ok = acquire_merge_lock(redis_client, "runner-a", repo_id="test-repo", timeout=5, lock_ttl=10)
        results.append(("a_acquired", ok))
        lock_held.set()
        time.sleep(0.5)
        release_merge_lock(redis_client, "runner-a", repo_id="test-repo")
        results.append(("a_released",))
        lock_released.set()

    def thread_b():
        lock_held.wait(timeout=3)
        ok = acquire_merge_lock(redis_client, "runner-b", repo_id="test-repo", timeout=5, lock_ttl=10)
        results.append(("b_acquired", ok))

    ta = threading.Thread(target=thread_a)
    tb = threading.Thread(target=thread_b)
    ta.start()
    tb.start()
    ta.join(timeout=8)
    tb.join(timeout=8)

    assert ("a_acquired", True) in results
    assert ("b_acquired", True) in results
    # a_released가 b_acquired 이전에 발생해야 한다 (FIFO 순서)
    a_rel_idx = next(i for i, r in enumerate(results) if r == ("a_released",))
    b_acq_idx = next(i for i, r in enumerate(results) if r[0] == "b_acquired")
    assert a_rel_idx < b_acq_idx


# ---------------------------------------------------------------------------
# 하위 호환 (repo_id=None → 글로벌 키)
# ---------------------------------------------------------------------------

def test_backward_compat_no_repo_id_B(redis_client):
    """B(Boundary): repo_id=None → 기존 글로벌 키 plan-runner:merge-lock 사용"""
    ok = acquire_merge_lock(redis_client, "runner-global", repo_id=None, timeout=3, lock_ttl=10)
    assert ok is True
    assert redis_client.get("plan-runner:merge-lock") == "runner-global"
    assert redis_client.get("plan-runner:merge-lock:None") is None
    release_merge_lock(redis_client, "runner-global", repo_id=None)
    assert redis_client.get("plan-runner:merge-lock") is None


# ---------------------------------------------------------------------------
# 큐 키 격리
# ---------------------------------------------------------------------------

def test_merge_lock_key_isolation_B(redis_client):
    """B(Boundary): repo-a lock 획득 + 큐 등록 → repo-b 큐에 영향 없음"""
    acquire_merge_lock(redis_client, "runner1", repo_id="repo-a", timeout=3, lock_ttl=10)
    # repo-b 큐 비어있어야 함
    assert redis_client.llen(get_merge_wait_queue_key("repo-b")) == 0
    release_merge_lock(redis_client, "runner1", repo_id="repo-a")
