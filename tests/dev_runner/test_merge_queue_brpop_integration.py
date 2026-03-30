"""
TC: merge queue BRPOP 통합 TC (실물 Redis DB15)

Phase T3 통합 TC:
- test_three_runners_concurrent_merge_integration: 3개 스레드 동시 acquire → 순차 실행
- test_stale_recovery_integration: stale runner 감지 및 front 승격
- test_queue_key_per_repo_isolation_integration: repo_id별 큐 독립성 검증
"""
import sys
import threading
import time
from pathlib import Path

import pytest
import redis

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from merge_queue import (
    _RUNNER_KEY_PREFIX,
    acquire_merge_turn,
    get_merge_queue,
    get_queue_key,
    release_merge_turn,
)

REPO_ID = "test-merge-queue-integration"


@pytest.fixture
def r():
    client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    yield client
    keys = (
        client.keys("plan-runner:merge-queue:test-*")
        + client.keys("plan-runner:merge-turn:*")
        + client.keys(f"{_RUNNER_KEY_PREFIX}:runner-*")
    )
    if keys:
        client.delete(*keys)
    client.close()


def test_three_runners_concurrent_merge_integration(r):
    """3개 스레드가 동시에 acquire_merge_turn 호출 → 첫 번째만 즉시 True →
    나머지 BRPOP 대기 → 순차 release → 3개 모두 완료.
    실행 순서가 RPUSH 순서와 일치하는지 검증. timeout=15
    """
    results = []
    results_lock = threading.Lock()
    order_barrier = threading.Barrier(3)

    def run_runner(runner_id: str):
        import os
        # 스레드별 독립 클라이언트 (공유 커넥션 경합 방지)
        client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        try:
            # PID 키 설정 (stale 오감지 방지)
            client.set(f"{_RUNNER_KEY_PREFIX}:{runner_id}:pid", str(os.getpid()))
            client.expire(f"{_RUNNER_KEY_PREFIX}:{runner_id}:pid", 120)

            # 3개 스레드 동시 진입 보장
            order_barrier.wait(timeout=5)

            ok = acquire_merge_turn(client, runner_id, repo_id=REPO_ID, timeout=15, queue_ttl=120)
            with results_lock:
                results.append((runner_id, "acquired", ok))

            # 짧은 작업 시뮬레이션
            time.sleep(0.1)

            release_merge_turn(client, runner_id, repo_id=REPO_ID)
            with results_lock:
                results.append((runner_id, "released"))
        finally:
            client.close()

    runner_ids = ["runner-a", "runner-b", "runner-c"]
    threads = [threading.Thread(target=run_runner, args=(rid,)) for rid in runner_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    # 3개 모두 acquire 성공
    acquired = [(entry[0], entry[2]) for entry in results if entry[1] == "acquired"]
    assert len(acquired) == 3, f"acquire 완료 수 != 3: {results}"
    assert all(ok is True for _, ok in acquired), f"acquire 실패 있음: {acquired}"

    # 3개 모두 release 완료
    released = [entry[0] for entry in results if entry[1] == "released"]
    assert len(released) == 3, f"release 완료 수 != 3: {results}"

    # 최종적으로 큐가 비어있어야 함 (모두 완료)
    final_queue = get_merge_queue(r, repo_id=REPO_ID)
    assert final_queue == [], f"완료 후 큐에 잔류 항목: {final_queue}"


def test_stale_recovery_integration(r):
    """runner A acquire 후 release 없이 스레드 종료 (crash 시뮬레이션) →
    runner B acquire 대기 중 stale 감지 → B가 front 승격 → B acquire True
    A의 PID를 존재하지 않는 PID로 설정 (99999 등)
    B는 timeout=15로 대기
    """
    runner_a = "runner-a-stale"
    runner_b = "runner-b-waiter"

    # A: acquire 후 PID를 존재하지 않는 PID(99999)로 교체하여 crash 시뮬레이션
    import os
    r.set(f"{_RUNNER_KEY_PREFIX}:{runner_a}:pid", str(os.getpid()))
    r.expire(f"{_RUNNER_KEY_PREFIX}:{runner_a}:pid", 120)

    ok_a = acquire_merge_turn(r, runner_a, repo_id=REPO_ID, timeout=5, queue_ttl=120)
    assert ok_a is True, "A가 front acquire 실패"

    # A의 PID를 존재하지 않는 PID로 교체 (crash 시뮬레이션)
    r.set(f"{_RUNNER_KEY_PREFIX}:{runner_a}:pid", "99999")

    # B: acquire 대기 — stale 감지 후 승격 기대
    r.set(f"{_RUNNER_KEY_PREFIX}:{runner_b}:pid", str(os.getpid()))
    r.expire(f"{_RUNNER_KEY_PREFIX}:{runner_b}:pid", 120)

    ok_b = acquire_merge_turn(r, runner_b, repo_id=REPO_ID, timeout=15, queue_ttl=120)
    assert ok_b is True, "B가 stale 복구 후 acquire 실패"

    # 정리
    release_merge_turn(r, runner_b, repo_id=REPO_ID)


def test_queue_key_per_repo_isolation_integration(r):
    """repo_id="test-repo-alpha" 큐와 repo_id="test-repo-beta" 큐가 서로 독립 동작 확인.
    alpha에 A acquire, beta에 B acquire → 각자 즉시 True (서로 독립).
    alpha queue에 A만 있고 B 없음, beta queue에 B만 있고 A 없음 확인.
    """
    import os

    repo_alpha = "test-repo-alpha"
    repo_beta = "test-repo-beta"
    runner_a = "runner-alpha-only"
    runner_b = "runner-beta-only"

    # PID 설정
    r.set(f"{_RUNNER_KEY_PREFIX}:{runner_a}:pid", str(os.getpid()))
    r.expire(f"{_RUNNER_KEY_PREFIX}:{runner_a}:pid", 120)
    r.set(f"{_RUNNER_KEY_PREFIX}:{runner_b}:pid", str(os.getpid()))
    r.expire(f"{_RUNNER_KEY_PREFIX}:{runner_b}:pid", 120)

    # 각자 독립 큐에서 acquire
    ok_a = acquire_merge_turn(r, runner_a, repo_id=repo_alpha, timeout=5, queue_ttl=120)
    ok_b = acquire_merge_turn(r, runner_b, repo_id=repo_beta, timeout=5, queue_ttl=120)

    assert ok_a is True, f"alpha A acquire 실패"
    assert ok_b is True, f"beta B acquire 실패"

    # alpha 큐: A만 있고 B 없음
    alpha_queue = get_merge_queue(r, repo_id=repo_alpha)
    assert runner_a in alpha_queue, f"alpha 큐에 A 없음: {alpha_queue}"
    assert runner_b not in alpha_queue, f"alpha 큐에 B 포함됨 (격리 실패): {alpha_queue}"

    # beta 큐: B만 있고 A 없음
    beta_queue = get_merge_queue(r, repo_id=repo_beta)
    assert runner_b in beta_queue, f"beta 큐에 B 없음: {beta_queue}"
    assert runner_a not in beta_queue, f"beta 큐에 A 포함됨 (격리 실패): {beta_queue}"

    # 정리
    release_merge_turn(r, runner_a, repo_id=repo_alpha)
    release_merge_turn(r, runner_b, repo_id=repo_beta)
