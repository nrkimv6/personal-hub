"""_recover_pending_merge merge_status 비일관성 수정 TC

R(Right): 정상 흐름 검증
B(Boundary): 경계 조건 검증
T3 통합: 실물 Redis DB15 사용
"""

import pytest
from unittest.mock import MagicMock, patch

RUNNER_KEY_PREFIX = "plan-runner:runners"


def _make_redis(data: dict | None = None):
    """테스트용 Redis 클라이언트 mock"""
    store = dict(data or {})
    client = MagicMock()
    client.get.side_effect = lambda key: store.get(key)
    client.set.side_effect = lambda key, val, **kw: store.update({key: val}) or None
    client.delete.side_effect = lambda *keys: [store.pop(k, None) for k in keys]
    return client, store


# ── Unit TCs (fakeredis 없이 mock 사용) ──────────────────────────────────────

class TestRecoverPendingMergeUnit:
    def _call(self, runner_id, redis_client, store, merge_status,
              release_fn=None, do_merge_fn=None):
        """실제 _recover_pending_merge 호출"""
        import sys
        import os
        scripts_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "scripts"
        )
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        from _dr_process_utils import _recover_pending_merge

        release_mock = release_fn or MagicMock()
        do_merge_mock = do_merge_fn or MagicMock()

        with patch("merge_queue.release_merge_turn", release_mock), \
             patch("_dr_plan_runner._do_inline_merge", do_merge_mock):
            _recover_pending_merge(runner_id, redis_client, merge_status)

        return release_mock, do_merge_mock

    def test_recover_merging_sets_none_right(self):
        """R: merge_status="merging" → release 후 merge_status 키 없음(None)"""
        redis_client, store = _make_redis()
        store[f"{RUNNER_KEY_PREFIX}:abc:merge_status"] = "merging"

        self._call("abc", redis_client, store, "merging")

        assert store.get(f"{RUNNER_KEY_PREFIX}:abc:merge_status") is None

    def test_recover_resolving_sets_none_right(self):
        """R: merge_status="resolving" → release 후 merge_status 키 없음(None)"""
        redis_client, store = _make_redis()
        store[f"{RUNNER_KEY_PREFIX}:abc:merge_status"] = "resolving"

        self._call("abc", redis_client, store, "resolving")

        assert store.get(f"{RUNNER_KEY_PREFIX}:abc:merge_status") is None

    def test_recover_queued_no_change_boundary(self):
        """B: merge_status="queued" → merge_status 변경 없음 (queued 유지)"""
        redis_client, store = _make_redis()
        store[f"{RUNNER_KEY_PREFIX}:abc:merge_status"] = "queued"

        self._call("abc", redis_client, store, "queued")

        assert store.get(f"{RUNNER_KEY_PREFIX}:abc:merge_status") == "queued"

    def test_recover_calls_do_inline_merge_right(self):
        """R: merge_status="merging" → release 후 _do_inline_merge 호출됨"""
        redis_client, store = _make_redis()
        do_merge_mock = MagicMock()

        self._call("abc", redis_client, store, "merging",
                   do_merge_fn=do_merge_mock)

        do_merge_mock.assert_called_once_with("abc", redis_client)

    def test_recover_sets_merge_requested_right(self):
        """R: merge_requested 없을 때 → _recover_pending_merge → merge_requested="1" 설정됨"""
        redis_client, store = _make_redis()

        self._call("abc", redis_client, store, "merging")

        assert store.get(f"{RUNNER_KEY_PREFIX}:abc:merge_requested") == "1"


# ── T3 통합 TC (실물 Redis DB15) ─────────────────────────────────────────────

@pytest.mark.integration
class TestRecoverPendingMergeIntegration:
    @pytest.fixture
    def real_redis(self):
        """실물 Redis DB15 연결"""
        import redis
        r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        try:
            r.ping()
        except Exception:
            pytest.fail("Redis DB15 연결 불가 — 통합 TC 스킵")
        yield r
        # 테스트 후 정리
        keys = r.keys(f"{RUNNER_KEY_PREFIX}:test_*")
        if keys:
            r.delete(*keys)

    def test_recover_merge_full_cycle_integration(self, real_redis):
        """T3 통합: 실물 Redis. runner가 merging → _recover_pending_merge → merge_status 키 없음 → _do_inline_merge mock 호출"""
        import sys
        import os
        scripts_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "scripts"
        )
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        from _dr_process_utils import _recover_pending_merge

        runner_id = "test_integration_runner"
        merge_status_key = f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status"
        merge_requested_key = f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested"

        # 초기 상태: merging
        real_redis.set(merge_status_key, "merging")
        assert real_redis.get(merge_status_key) == "merging"

        do_merge_mock = MagicMock()
        with patch("merge_queue.release_merge_turn", MagicMock()), \
             patch("_dr_plan_runner._do_inline_merge", do_merge_mock):
            _recover_pending_merge(runner_id, real_redis, "merging")

        # merge_status 키 삭제됨
        assert real_redis.get(merge_status_key) is None
        # _do_inline_merge 호출됨
        do_merge_mock.assert_called_once_with(runner_id, real_redis)
        # merge_requested 설정됨
        assert real_redis.get(merge_requested_key) == "1"
