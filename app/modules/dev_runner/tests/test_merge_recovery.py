"""listener 재시작 시 merge 복구 로직 테스트

_recover_pending_merge, _cleanup_process_state, _reconnect_surviving_runners의
resolving 상태 처리를 로직 복제 방식으로 검증한다.
"""

import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

# ── 테스트 대상 상수 ─────────────────────────────────────────────────────────

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
MERGE_ACTIVE_STATUSES = ("queued", "merging", "pending_merge", "resolving")
LOG_CHANNEL_PREFIX = "plan-runner:logs"


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _make_redis(data: dict | None = None):
    """테스트용 Redis 클라이언트 mock"""
    store = dict(data or {})
    client = MagicMock()
    client.get.side_effect = lambda key: store.get(key)
    client.set.side_effect = lambda key, val, **kw: store.update({key: val}) or None
    client.delete.side_effect = lambda key: store.pop(key, None)
    client.smembers.side_effect = lambda key: store.get(key, set())
    client.srem.return_value = 1
    client.publish.return_value = 0
    return client, store


# ── _recover_pending_merge 로직 복제 ─────────────────────────────────────────

def _recover_pending_merge_impl(runner_id, redis_client, merge_status,
                                 release_fn, do_merge_fn):
    """listener의 _recover_pending_merge 로직 복제"""
    if merge_status in ("merging", "resolving"):
        try:
            release_fn(redis_client, runner_id)
        except Exception:
            pass
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "queued")
        _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
        if not _mr:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")

    elif merge_status in ("queued", "pending_merge") or merge_status is None:
        _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
        if not _mr:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
    else:
        return  # 복구 불필요

    do_merge_fn(runner_id, redis_client)


# ── _cleanup_process_state 보호 가드 로직 복제 ───────────────────────────────

def _should_block_cleanup(runner_id, redis_client, reason):
    """보호 가드: reconnect_/heartbeat_ reason + MERGE_ACTIVE_STATUSES → True (차단)"""
    if reason and reason.startswith(("reconnect_", "heartbeat_")):
        merge_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        if merge_status in MERGE_ACTIVE_STATUSES:
            return True
    return False


# ── _reconnect_surviving_runners 복구 조건 로직 복제 ─────────────────────────

def _reconnect_needs_recovery(merge_requested, merge_status):
    """merge_requested 또는 merge_status 활성 → 복구 필요"""
    return bool(merge_requested) or merge_status in MERGE_ACTIVE_STATUSES


# ── TestRecoverPendingMerge ───────────────────────────────────────────────────

class TestRecoverPendingMerge:
    def test_resolving_releases_lock(self):
        """R(Right): merge_status="resolving" → release_fn 호출"""
        redis_client, store = _make_redis()
        release_fn = MagicMock()
        do_merge_fn = MagicMock()

        _recover_pending_merge_impl("abc", redis_client, "resolving", release_fn, do_merge_fn)

        release_fn.assert_called_once_with(redis_client, "abc")

    def test_resolving_resets_status_to_queued(self):
        """R(Right): merge_status="resolving" → merge_status="queued" 재설정"""
        redis_client, store = _make_redis()

        _recover_pending_merge_impl("abc", redis_client, "resolving",
                                    MagicMock(), MagicMock())

        assert store.get(f"{RUNNER_KEY_PREFIX}:abc:merge_status") == "queued"

    def test_resolving_sets_merge_requested_flag(self):
        """R(Right): resolving 복구 후 merge_requested 플래그 설정"""
        redis_client, store = _make_redis()

        _recover_pending_merge_impl("abc", redis_client, "resolving",
                                    MagicMock(), MagicMock())

        assert store.get(f"{RUNNER_KEY_PREFIX}:abc:merge_requested") == "1"

    def test_resolving_calls_do_inline_merge(self):
        """R(Right): resolving 복구 후 _do_inline_merge() 호출"""
        redis_client, _ = _make_redis()
        do_merge_fn = MagicMock()

        _recover_pending_merge_impl("abc", redis_client, "resolving",
                                    MagicMock(), do_merge_fn)

        do_merge_fn.assert_called_once_with("abc", redis_client)

    def test_conflict_skips_recovery(self):
        """B(Boundary): merge_status="conflict" → 복구 불필요, do_merge_fn 미호출"""
        redis_client, _ = _make_redis()
        do_merge_fn = MagicMock()

        _recover_pending_merge_impl("abc", redis_client, "conflict",
                                    MagicMock(), do_merge_fn)

        do_merge_fn.assert_not_called()

    def test_merged_skips_recovery(self):
        """B(Boundary): merge_status="merged" → 복구 스킵"""
        redis_client, _ = _make_redis()
        do_merge_fn = MagicMock()

        _recover_pending_merge_impl("abc", redis_client, "merged",
                                    MagicMock(), do_merge_fn)

        do_merge_fn.assert_not_called()


# ── TestCleanupProcessStateMergeGuard ────────────────────────────────────────

class TestCleanupProcessStateMergeGuard:
    def test_rejects_resolving_on_reconnect(self):
        """R(Right): reason="reconnect_orphan" + merge_status="resolving" → cleanup 거부"""
        redis_client, _ = _make_redis({
            f"{RUNNER_KEY_PREFIX}:abc:merge_status": "resolving",
        })

        blocked = _should_block_cleanup("abc", redis_client, "reconnect_orphan")

        assert blocked is True

    def test_rejects_all_active_statuses_on_reconnect(self):
        """R(Right): MERGE_ACTIVE_STATUSES 모든 상태에서 reconnect_* reason → 차단"""
        for status in MERGE_ACTIVE_STATUSES:
            redis_client, _ = _make_redis({
                f"{RUNNER_KEY_PREFIX}:abc:merge_status": status,
            })
            assert _should_block_cleanup("abc", redis_client, "reconnect_orphan") is True

    def test_allows_resolving_on_normal_cleanup(self):
        """B(Boundary): reason="process_cleanup" + merge_status="resolving" → cleanup 진행"""
        redis_client, _ = _make_redis({
            f"{RUNNER_KEY_PREFIX}:abc:merge_status": "resolving",
        })

        blocked = _should_block_cleanup("abc", redis_client, "process_cleanup")

        assert blocked is False

    def test_allows_conflict_on_reconnect(self):
        """B(Boundary): merge_status="conflict"은 MERGE_ACTIVE_STATUSES 아님 → cleanup 허용"""
        redis_client, _ = _make_redis({
            f"{RUNNER_KEY_PREFIX}:abc:merge_status": "conflict",
        })

        blocked = _should_block_cleanup("abc", redis_client, "reconnect_orphan")

        assert blocked is False


# ── TestReconnectNeedsRecovery ────────────────────────────────────────────────

class TestReconnectNeedsRecovery:
    def test_resolving_triggers_recovery(self):
        """R(Right): merge_status="resolving" → 복구 필요"""
        assert _reconnect_needs_recovery(None, "resolving") is True

    def test_merge_requested_triggers_recovery(self):
        """R(Right): merge_requested=True → 복구 필요"""
        assert _reconnect_needs_recovery("1", None) is True

    def test_all_active_statuses_trigger_recovery(self):
        """R(Right): MERGE_ACTIVE_STATUSES 모든 상태 → 복구 필요"""
        for status in MERGE_ACTIVE_STATUSES:
            assert _reconnect_needs_recovery(None, status) is True

    def test_conflict_does_not_trigger_recovery(self):
        """B(Boundary): merge_status="conflict" → 복구 불필요"""
        assert _reconnect_needs_recovery(None, "conflict") is False

    def test_merged_does_not_trigger_recovery(self):
        """B(Boundary): merge_status="merged" → 복구 불필요"""
        assert _reconnect_needs_recovery(None, "merged") is False

    def test_none_status_no_merge_requested_no_recovery(self):
        """B(Boundary): 상태 없고 merge_requested도 없으면 복구 불필요"""
        assert _reconnect_needs_recovery(None, None) is False
