"""
test_cleanup_runners.py - cleanup_test_runners.py 단위테스트

fakeredis 또는 db=15 real redis 사용
"""
import os
import sys
import pytest

try:
    import fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

_SCRIPTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from cleanup_test_runners import (
    scan_dead_runners,
    scan_incomplete_runners,
    delete_runner_keys,
    _is_pid_alive,
    KEY_PREFIX,
    ACTIVE_SET_KEY,
)


def make_redis():
    if HAS_FAKEREDIS:
        return fakeredis.FakeRedis(decode_responses=True)
    import redis as _redis
    r = _redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    r.flushdb()
    return r


def seed_runner(r, runner_id, pid, branch="main", status="running"):
    r.set(f"{KEY_PREFIX}{runner_id}:pid", str(pid))
    r.set(f"{KEY_PREFIX}{runner_id}:branch", branch)
    r.set(f"{KEY_PREFIX}{runner_id}:status", status)
    r.sadd(ACTIVE_SET_KEY, runner_id)


class TestScanDeadRunners:
    def test_dead_pid_detected(self):
        r = make_redis()
        seed_runner(r, "runner-dead-1", pid=999999999, branch="test_branch")
        dead = scan_dead_runners(r)
        ids = [d["runner_id"] for d in dead]
        assert "runner-dead-1" in ids

    def test_alive_pid_skipped(self):
        r = make_redis()
        live_pid = os.getpid()
        seed_runner(r, "runner-alive-1", pid=live_pid)
        dead = scan_dead_runners(r)
        ids = [d["runner_id"] for d in dead]
        assert "runner-alive-1" not in ids

    def test_test_only_filter(self):
        r = make_redis()
        seed_runner(r, "runner-test-1", pid=999999998, branch="test_e2e")
        seed_runner(r, "runner-prod-1", pid=999999997, branch="feature/foo")
        dead = scan_dead_runners(r, test_only=True)
        ids = [d["runner_id"] for d in dead]
        assert "runner-test-1" in ids
        assert "runner-prod-1" not in ids

    def test_returns_keys_list(self):
        r = make_redis()
        seed_runner(r, "runner-keys-1", pid=999999996)
        dead = scan_dead_runners(r)
        entry = next((d for d in dead if d["runner_id"] == "runner-keys-1"), None)
        assert entry is not None
        assert len(entry["keys"]) > 0

    def test_dead_entry_has_branch_and_status(self):
        r = make_redis()
        seed_runner(r, "runner-meta-1", pid=999999995, branch="test_meta", status="running")
        dead = scan_dead_runners(r)
        entry = next((d for d in dead if d["runner_id"] == "runner-meta-1"), None)
        assert entry is not None
        assert entry["branch"] == "test_meta"
        assert entry["status"] == "running"


class TestBoundary:
    def test_empty_redis_returns_empty(self):
        r = make_redis()
        assert scan_dead_runners(r) == []

    def test_incomplete_runner_no_pid_detected(self):
        r = make_redis()
        runner_id = "runner-incomplete-1"
        r.set(f"{KEY_PREFIX}{runner_id}:branch", "test_branch")
        r.set(f"{KEY_PREFIX}{runner_id}:status", "running")
        incomplete = scan_incomplete_runners(r)
        ids = [d["runner_id"] for d in incomplete]
        assert runner_id in ids

    def test_incomplete_test_only_filter(self):
        r = make_redis()
        r.set(f"{KEY_PREFIX}incomplete-test:branch", "test_foo")
        r.set(f"{KEY_PREFIX}incomplete-test:status", "running")
        r.set(f"{KEY_PREFIX}incomplete-prod:branch", "feature/bar")
        r.set(f"{KEY_PREFIX}incomplete-prod:status", "running")
        incomplete = scan_incomplete_runners(r, test_only=True)
        ids = [d["runner_id"] for d in incomplete]
        assert "incomplete-test" in ids
        assert "incomplete-prod" not in ids

    def test_incomplete_not_in_dead_scan(self):
        r = make_redis()
        runner_id = "runner-nopid-1"
        r.set(f"{KEY_PREFIX}{runner_id}:branch", "test_foo")
        r.set(f"{KEY_PREFIX}{runner_id}:status", "running")
        dead = scan_dead_runners(r)
        ids = [d["runner_id"] for d in dead]
        assert runner_id not in ids


class TestForceDelete:
    def test_delete_removes_keys(self):
        r = make_redis()
        seed_runner(r, "runner-del-1", pid=999999990, branch="test_x")
        dead = scan_dead_runners(r)
        assert len(dead) > 0
        delete_runner_keys(r, dead)
        assert r.get(f"{KEY_PREFIX}runner-del-1:pid") is None
        assert r.get(f"{KEY_PREFIX}runner-del-1:status") is None

    def test_delete_removes_from_active_set(self):
        r = make_redis()
        seed_runner(r, "runner-set-1", pid=999999989)
        assert r.sismember(ACTIVE_SET_KEY, "runner-set-1")
        dead = scan_dead_runners(r)
        delete_runner_keys(r, dead)
        assert not r.sismember(ACTIVE_SET_KEY, "runner-set-1")

    def test_delete_returns_positive_count(self):
        r = make_redis()
        seed_runner(r, "runner-cnt-1", pid=999999988)
        dead = scan_dead_runners(r)
        deleted = delete_runner_keys(r, dead)
        assert deleted > 0

    def test_delete_empty_list(self):
        r = make_redis()
        deleted = delete_runner_keys(r, [])
        assert deleted == 0


class TestError:
    def test_pid_alive_invalid_pid_returns_false(self):
        assert _is_pid_alive(-1) is False
        assert _is_pid_alive(0) is False

    def test_pid_alive_dead_pid_returns_false(self):
        assert _is_pid_alive(999999999) is False

    def test_pid_alive_current_process(self):
        assert _is_pid_alive(os.getpid()) is True
