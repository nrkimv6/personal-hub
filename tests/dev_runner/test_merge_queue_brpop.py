"""
merge_queue.py (BRPOP 기반) 단위 테스트

실물 Redis DB15 사용. fakeredis는 BRPOP threading 테스트에 부적합하여 사용 금지.
"""

import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import redis

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from merge_queue import (
    _ENQUEUE_LUA,
    _RUNNER_KEY_PREFIX,
    _get_repo_id,
    _remove_if_stale,
    acquire_merge_turn,
    get_merge_queue,
    get_merge_queue_length,
    get_queue_key,
    get_turn_key,
    release_merge_turn,
)

REPO_ID = "test-merge-queue-brpop"


def _cleanup_redis_patterns(client, *patterns) -> None:
    keys_to_delete = []
    for pattern in patterns:
        keys_to_delete.extend(list(client.scan_iter(pattern, count=200)))
    if keys_to_delete:
        client.delete(*keys_to_delete)


def _close_redis_client(client) -> None:
    try:
        client.close()
    finally:
        try:
            client.connection_pool.disconnect()
        except Exception:
            pass


@pytest.fixture
def r():
    client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    _cleanup_redis_patterns(
        client,
        "plan-runner:merge-queue:*",
        "plan-runner:merge-turn:*",
        "plan-runner:runners:runner-*",
    )
    try:
        yield client
    finally:
        _cleanup_redis_patterns(
            client,
            "plan-runner:merge-queue:*",
            "plan-runner:merge-turn:*",
            "plan-runner:runners:runner-*",
        )
        _close_redis_client(client)


# ── TC 1 ──────────────────────────────────────────────────────────────────────
def test_get_queue_key_right():
    assert get_queue_key("my-repo") == "plan-runner:merge-queue:my-repo"


# ── TC 2 ──────────────────────────────────────────────────────────────────────
def test_get_turn_key_right():
    assert get_turn_key("runner-1") == "plan-runner:merge-turn:runner-1"


# ── TC 3 ──────────────────────────────────────────────────────────────────────
def test_get_repo_id_right():
    result = _get_repo_id(Path("D:/work/project"))
    assert result != ""
    assert result == result.lower()
    assert "/" not in result
    assert "\\" not in result
    assert "-" in result or result.isalnum()


# ── TC 4 ──────────────────────────────────────────────────────────────────────
def test_get_merge_queue_empty_boundary(r):
    result = get_merge_queue(r, repo_id=REPO_ID)
    assert result == []


# ── TC 5 ──────────────────────────────────────────────────────────────────────
def test_get_merge_queue_length_empty_boundary(r):
    result = get_merge_queue_length(r, repo_id=REPO_ID)
    assert result == 0


# ── TC 6 ──────────────────────────────────────────────────────────────────────
def test_get_merge_queue_right(r):
    queue_key = get_queue_key(REPO_ID)
    r.rpush(queue_key, "A", "B")
    result = get_merge_queue(r, repo_id=REPO_ID)
    assert result == ["A", "B"]


# ── TC 7 ──────────────────────────────────────────────────────────────────────
def test_get_merge_queue_length_right(r):
    assert get_merge_queue_length(r, repo_id=REPO_ID) == 0
    queue_key = get_queue_key(REPO_ID)
    r.rpush(queue_key, "A", "B", "C")
    assert get_merge_queue_length(r, repo_id=REPO_ID) == 3


# ── TC 8 ──────────────────────────────────────────────────────────────────────
def test_acquire_release_turn_right(r):
    """단일 runner — LINDEX 0 == me로 즉시 True 반환 (BRPOP 호출 없음)."""
    acquired = acquire_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID, timeout=10, queue_ttl=60)
    assert acquired is True

    released = release_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID)
    assert released is True

    queue = get_merge_queue(r, repo_id=REPO_ID)
    assert queue == []


# ── TC 9 ──────────────────────────────────────────────────────────────────────
def test_release_empty_queue_right(r):
    """A만 큐 → A release → next 없음 → signal 미발생, True 반환."""
    queue_key = get_queue_key(REPO_ID)
    r.rpush(queue_key, "runner-A")

    result = release_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID)
    assert result is True

    # 큐 비어있음
    assert r.llen(queue_key) == 0
    # signal 없음
    assert r.exists(get_turn_key("runner-A")) == 0


# ── TC 10 ─────────────────────────────────────────────────────────────────────
def test_release_signals_next_right(r):
    """A, B 큐 → A release → merge-turn:B 키에 'go' 존재."""
    queue_key = get_queue_key(REPO_ID)
    r.rpush(queue_key, "runner-A", "runner-B")

    release_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID)

    turn_key_b = get_turn_key("runner-B")
    assert r.llen(turn_key_b) >= 1
    val = r.lrange(turn_key_b, 0, -1)
    assert "go" in val


# ── TC 11 ─────────────────────────────────────────────────────────────────────
def test_double_release_boundary(r):
    """같은 runner_id로 release 2회 → 두 번째는 False 반환."""
    queue_key = get_queue_key(REPO_ID)
    r.rpush(queue_key, "runner-A")

    first = release_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID)
    second = release_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID)

    assert first is True
    assert second is False


# ── TC 12 ─────────────────────────────────────────────────────────────────────
def test_acquire_empty_repo_id_boundary(r):
    """repo_id=None에서도 turn 획득이 정상 동작해야 한다."""
    acquired = acquire_merge_turn(r, runner_id="runner-A", repo_id=None, timeout=10, queue_ttl=60)
    assert acquired is True


# ── TC 13 ─────────────────────────────────────────────────────────────────────
def test_acquire_duplicate_enqueue_boundary(r):
    """같은 runner_id로 _ENQUEUE_LUA 2회 시도 → 큐에 1건만 존재."""
    queue_key = get_queue_key(REPO_ID)
    r.eval(_ENQUEUE_LUA, 1, queue_key, "runner-A")
    r.eval(_ENQUEUE_LUA, 1, queue_key, "runner-A")
    assert r.llen(queue_key) == 1
    assert r.lrange(queue_key, 0, -1) == ["runner-A"]


# ── TC 14 ─────────────────────────────────────────────────────────────────────
def test_stale_front_removal_error(r):
    """PID dead 판정 → LREM + 다음 runner에 signal."""
    queue_key = get_queue_key(REPO_ID)
    r.rpush(queue_key, "runner-dead", "runner-next")

    # PID 키 설정 (항상 죽은 PID로 판정되는 값)
    pid_key = f"{_RUNNER_KEY_PREFIX}:runner-dead:pid"
    r.set(pid_key, "-1")
    removed = _remove_if_stale(r, "runner-dead", REPO_ID)

    assert removed is True
    # runner-dead 큐에서 제거됨
    queue = r.lrange(queue_key, 0, -1)
    assert "runner-dead" not in queue
    # runner-next에 signal 전달
    turn_key_next = get_turn_key("runner-next")
    assert r.llen(turn_key_next) >= 1

    # 정리
    r.delete(pid_key)


# ── TC 15 ─────────────────────────────────────────────────────────────────────
def test_stale_front_alive_right(r):
    """front runner PID 살아있음 → _remove_if_stale → 제거 안 함, False 반환."""
    queue_key = get_queue_key(REPO_ID)
    r.rpush(queue_key, "runner-alive", "runner-next")

    pid_key = f"{_RUNNER_KEY_PREFIX}:runner-alive:pid"
    r.set(pid_key, str(os.getpid()))
    removed = _remove_if_stale(r, "runner-alive", REPO_ID)

    assert removed is False
    queue = r.lrange(queue_key, 0, -1)
    assert "runner-alive" in queue

    # 정리
    r.delete(pid_key)


# ── TC 16 ─────────────────────────────────────────────────────────────────────
def test_acquire_turn_fifo_boundary(r):
    """threading: A acquire(즉시 True), B acquire 시작(BRPOP 대기) → A release → B True."""
    results = {}
    b_started = threading.Event()
    b_done = threading.Event()

    def run_b():
        b_client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        try:
            b_started.set()
            results["B"] = acquire_merge_turn(b_client, runner_id="runner-B", repo_id=REPO_ID, timeout=10, queue_ttl=60)
        finally:
            _close_redis_client(b_client)
            b_done.set()

    # A가 먼저 큐 진입
    results["A"] = acquire_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID, timeout=10, queue_ttl=60)
    assert results["A"] is True

    t = threading.Thread(target=run_b, daemon=True)
    t.start()
    b_started.wait(timeout=2)
    time.sleep(0.2)  # B가 BRPOP 대기 상태에 진입하도록 여유

    # A release → B 깨어남
    release_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID)

    assert b_done.wait(timeout=10), "runner-B 스레드 완료 타임아웃"
    t.join(timeout=10)
    assert not t.is_alive(), "runner-B 스레드가 종료되지 않음"

    assert results.get("B") is True

    # 정리
    release_merge_turn(r, runner_id="runner-B", repo_id=REPO_ID)


# ── TC 17 ─────────────────────────────────────────────────────────────────────
def test_acquire_turn_three_runners_boundary(r):
    """threading: A, B, C 순서 acquire → A→B→C 순서로 turn 획득."""
    results = {}
    order = []
    order_lock = threading.Lock()

    b_started = threading.Event()
    c_started = threading.Event()
    b_done = threading.Event()
    c_done = threading.Event()

    def run_b():
        b_client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        try:
            b_started.set()
            ok = acquire_merge_turn(b_client, runner_id="runner-B", repo_id=REPO_ID, timeout=10, queue_ttl=60)
            results["B"] = ok
            if ok:
                with order_lock:
                    order.append("B")
            release_merge_turn(b_client, runner_id="runner-B", repo_id=REPO_ID)
        finally:
            _close_redis_client(b_client)
            b_done.set()

    def run_c():
        c_client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        try:
            c_started.set()
            ok = acquire_merge_turn(c_client, runner_id="runner-C", repo_id=REPO_ID, timeout=10, queue_ttl=60)
            results["C"] = ok
            if ok:
                with order_lock:
                    order.append("C")
        finally:
            _close_redis_client(c_client)
            c_done.set()

    # A 먼저 진입
    results["A"] = acquire_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID, timeout=10, queue_ttl=60)
    assert results["A"] is True
    with order_lock:
        order.append("A")

    tb = threading.Thread(target=run_b, daemon=True)
    tc = threading.Thread(target=run_c, daemon=True)
    tb.start()
    b_started.wait(timeout=2)

    # FIFO 보장을 위해 B가 먼저 큐에 들어간 것을 확인한 뒤 C 시작
    for _ in range(20):
        if get_merge_queue(r, repo_id=REPO_ID)[:2] == ["runner-A", "runner-B"]:
            break
        time.sleep(0.05)
    else:
        pytest.fail("runner-B enqueue 확인 실패")

    tc.start()
    c_started.wait(timeout=2)
    for _ in range(20):
        if get_merge_queue(r, repo_id=REPO_ID)[:3] == ["runner-A", "runner-B", "runner-C"]:
            break
        time.sleep(0.05)
    else:
        pytest.fail("runner-C enqueue 확인 실패")

    # A release
    release_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID)

    assert b_done.wait(timeout=10), "runner-B 스레드 완료 타임아웃"
    assert c_done.wait(timeout=10), "runner-C 스레드 완료 타임아웃"
    tb.join(timeout=10)
    tc.join(timeout=10)
    assert not tb.is_alive(), "runner-B 스레드가 종료되지 않음"
    assert not tc.is_alive(), "runner-C 스레드가 종료되지 않음"

    assert results.get("B") is True
    assert results.get("C") is True
    # FIFO: A가 먼저, B가 A 다음으로 enqueue됐으므로 B → C 순서
    assert order[0] == "A"
    assert order[1] == "B"
    assert order[2] == "C"

    # 정리
    release_merge_turn(r, runner_id="runner-C", repo_id=REPO_ID)


# ── TC 18 ─────────────────────────────────────────────────────────────────────
def test_acquire_turn_timeout_error(r):
    """timeout=2, A가 release 안 함 → B acquire 2초 후 False + 큐에서 제거."""
    import os as _os
    # A 먼저 진입 (release 안 함) — PID 키 설정으로 stale 오감지 방지
    a_acquired = acquire_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID, timeout=10, queue_ttl=60)
    assert a_acquired is True
    r.set(f"{_RUNNER_KEY_PREFIX}:runner-A:pid", str(_os.getpid()))
    r.set(f"{_RUNNER_KEY_PREFIX}:runner-A:status", "merging")

    results = {}
    done_event = threading.Event()

    def run_b():
        b_client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        try:
            results["B"] = acquire_merge_turn(
                b_client, runner_id="runner-B", repo_id=REPO_ID, timeout=2, queue_ttl=60
            )
        finally:
            _close_redis_client(b_client)
            done_event.set()

    t = threading.Thread(target=run_b, daemon=True)
    t.start()
    assert done_event.wait(timeout=8), "runner-B 스레드 완료 타임아웃"
    t.join(timeout=8)
    assert not t.is_alive(), "runner-B 스레드가 종료되지 않음"

    assert results.get("B") is False
    # B가 큐에서 제거됨
    queue = get_merge_queue(r, repo_id=REPO_ID)
    assert "runner-B" not in queue

    # 정리
    release_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID)


# ── TC 19 ─────────────────────────────────────────────────────────────────────
def test_acquire_after_stale_removal_right(r):
    """threading: A acquire, B 대기 → A의 PID 키를 죽은 PID처럼 조작 → B stale 감지 후 승격 → True."""
    results = {}
    b_started = threading.Event()
    b_done = threading.Event()

    def run_b():
        b_client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        try:
            b_started.set()
            results["B"] = acquire_merge_turn(
                b_client, runner_id="runner-B", repo_id=REPO_ID, timeout=8, queue_ttl=60
            )
        finally:
            _close_redis_client(b_client)
            b_done.set()

    # A 진입
    a_acquired = acquire_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID, timeout=10, queue_ttl=60)
    assert a_acquired is True

    t = threading.Thread(target=run_b, daemon=True)
    t.start()
    b_started.wait(timeout=2)
    time.sleep(0.3)  # B가 BRPOP 루프에 진입하도록

    # A의 PID 키를 죽은 PID로 조작 (ProcessLookupError 유발)
    pid_key = f"{_RUNNER_KEY_PREFIX}:runner-A:pid"
    r.set(pid_key, "99999")

    # B가 5초 BRPOP timeout 후 stale 감지 → 승격 → True 반환 기다림
    assert b_done.wait(timeout=8), "runner-B 스레드 완료 타임아웃"
    t.join(timeout=8)
    assert not t.is_alive(), "runner-B 스레드가 종료되지 않음"

    assert results.get("B") is True

    # 정리
    r.delete(pid_key)
    release_merge_turn(r, runner_id="runner-B", repo_id=REPO_ID)


# ── TC 20 ─────────────────────────────────────────────────────────────────────
def test_acquire_cleans_stale_turn_key_right(r):
    """merge-turn:B에 잔존 'go'가 있어도 acquire 시 stale signal을 정리하고 즉시 turn을 얻는다."""
    turn_key_b = get_turn_key("runner-B")

    # 잔존 signal 삽입
    r.lpush(turn_key_b, "go")

    # acquire: 내부에서 DEL turn_key 후 enqueue, front면 즉시 True
    result = acquire_merge_turn(r, runner_id="runner-B", repo_id=REPO_ID, timeout=10, queue_ttl=60)
    assert result is True
    assert r.lrange(turn_key_b, 0, -1) == []
    assert get_merge_queue(r, repo_id=REPO_ID) == ["runner-B"]

    # 정리
    release_merge_turn(r, runner_id="runner-B", repo_id=REPO_ID)


# ── TC 21 ─────────────────────────────────────────────────────────────────────
def test_acquire_queue_expired_boundary(r):
    """threading: A acquire, B 대기 → 큐 키 DELETE → B가 큐 소멸 감지 후 False."""
    results = {}
    b_started = threading.Event()
    b_done = threading.Event()

    def run_b():
        b_client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        try:
            b_started.set()
            results["B"] = acquire_merge_turn(
                b_client, runner_id="runner-B", repo_id=REPO_ID, timeout=8, queue_ttl=60
            )
        finally:
            _close_redis_client(b_client)
            b_done.set()

    # A 진입
    a_acquired = acquire_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID, timeout=10, queue_ttl=60)
    assert a_acquired is True

    t = threading.Thread(target=run_b, daemon=True)
    t.start()
    b_started.wait(timeout=2)
    time.sleep(0.3)  # B가 BRPOP 루프에 진입하도록

    # 큐 키 강제 삭제 (EXPIRE 만료 시뮬레이션)
    queue_key = get_queue_key(REPO_ID)
    r.delete(queue_key)

    assert b_done.wait(timeout=8), "runner-B 스레드 완료 타임아웃"
    t.join(timeout=8)
    assert not t.is_alive(), "runner-B 스레드가 종료되지 않음"

    assert results.get("B") is False
    # 정리
    release_merge_turn(r, runner_id="runner-A", repo_id=REPO_ID)
