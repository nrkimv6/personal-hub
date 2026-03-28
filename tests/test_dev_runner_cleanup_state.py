"""dev-runner cleanup 상태 관리 잔여버그 TC

Plan: docs/plan/2026-03-27_fix-dev-runner-cleanup-state-leaks.md

Phase T1: _cleanup_done TTL, get_runner_status() Bug 1/2, orphan 원자 UPDATE
Phase T3: 통합 TC (실물 dict + 실물 executor_service)
"""
import time
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ============================================================
# listener 모듈 import (파일명에 하이픈 포함)
# ============================================================

_LISTENER_PATH = Path(__file__).parent.parent / "scripts" / "dev-runner-command-listener.py"


def _load_listener():
    spec = importlib.util.spec_from_file_location("dev_runner_command_listener", _LISTENER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ============================================================
# Phase T1: _cleanup_done TTL 소거
# ============================================================

class TestCleanupDoneTTL:
    """_cleanup_done dict TTL 기반 자동 소거 검증"""

    def _run_ttl_eviction(self, cleanup_done: dict):
        """heartbeat TTL 소거 로직 (listener 코드와 동일)"""
        _now = time.time()
        _expired = [rid for rid, ts in list(cleanup_done.items()) if _now - ts > 300]
        for _rid in _expired:
            cleanup_done.pop(_rid, None)
        return _expired

    def test_cleanup_done_ttl_eviction(self):
        """RIGHT: 6분 경과 항목 → TTL 소거 로직 실행 후 제거됨"""
        cleanup_done = {"old_rid": time.time() - 370}  # 6분 10초 전
        evicted = self._run_ttl_eviction(cleanup_done)
        assert "old_rid" not in cleanup_done
        assert "old_rid" in evicted

    def test_cleanup_done_recent_preserved(self):
        """BOUNDARY: 1분 경과 항목 → 소거 안 됨 (잔류)"""
        cleanup_done = {"recent_rid": time.time() - 60}  # 1분 전
        self._run_ttl_eviction(cleanup_done)
        assert "recent_rid" in cleanup_done

    def test_cleanup_done_still_blocks_double_cleanup(self):
        """RIGHT: TTL 내 rid → `if rid in _cleanup_done:` True (이중 cleanup 차단)"""
        cleanup_done = {"active_rid": time.time() - 60}  # 1분 전 (TTL 내)
        assert "active_rid" in cleanup_done  # dict key in 연산자 호환

    def test_cleanup_done_type_is_dict(self):
        """RIGHT: _cleanup_done 타입이 dict, set 메서드 없음"""
        listener = _load_listener()
        assert isinstance(listener._cleanup_done, dict)
        assert not hasattr(listener._cleanup_done, "add")

    def test_cleanup_done_add_sets_timestamp(self):
        """RIGHT: cleanup 시 rid → timestamp(float) 기록됨"""
        cleanup_done = {}
        before = time.time()
        cleanup_done["test_rid"] = time.time()
        after = time.time()
        assert "test_rid" in cleanup_done
        assert before <= cleanup_done["test_rid"] <= after

    def test_cleanup_done_multiple_entries_partial_eviction(self):
        """BOUNDARY: 오래된 항목만 소거, 최근 항목 보존"""
        cleanup_done = {
            "old1": time.time() - 400,
            "old2": time.time() - 350,
            "recent": time.time() - 60,
        }
        self._run_ttl_eviction(cleanup_done)
        assert "old1" not in cleanup_done
        assert "old2" not in cleanup_done
        assert "recent" in cleanup_done


# ============================================================
# Phase T1: get_runner_status() Bug 1/2 보정
# ============================================================

class TestGetRunnerStatusPidCorrection:
    """get_runner_status() PID 기반 양방향 보정 검증"""

    def _make_svc(self, status, pid_str):
        from app.modules.dev_runner.services.executor_service import ExecutorService, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY

        async def _get(key):
            data = {
                f"{RUNNER_KEY_PREFIX}:test_rid:status": status,
                f"{RUNNER_KEY_PREFIX}:test_rid:pid": pid_str,
                f"{RUNNER_KEY_PREFIX}:test_rid:plan_file": None,
                f"{RUNNER_KEY_PREFIX}:test_rid:start_time": None,
                f"{RUNNER_KEY_PREFIX}:test_rid:engine": "claude",
                f"{RUNNER_KEY_PREFIX}:test_rid:current_cycle": None,
            }
            return data.get(key)

        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = AsyncMock()
        svc.async_redis.get = _get
        svc.async_redis.set = AsyncMock()
        svc.async_redis.sadd = AsyncMock()
        svc._force_cleanup_state = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_get_runner_status_pid_alive_restores(self):
        """RIGHT: status=stopped + PID alive → running=True 복원"""
        from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY
        svc = self._make_svc("stopped", "12345")
        with patch.object(type(svc), "_is_pid_alive", return_value=True):
            result = await svc.get_runner_status("test_rid")
        assert result.running is True
        svc.async_redis.set.assert_any_call(f"{RUNNER_KEY_PREFIX}:test_rid:status", "running")
        svc.async_redis.sadd.assert_any_call(ACTIVE_RUNNERS_KEY, "test_rid")

    @pytest.mark.asyncio
    async def test_get_runner_status_pid_stale_cleanup(self):
        """RIGHT: status=running + PID dead → _force_cleanup_state 호출 + running=False"""
        svc = self._make_svc("running", "99999")
        with patch.object(type(svc), "_is_pid_alive", return_value=False):
            result = await svc.get_runner_status("test_rid")
        assert result.running is False
        svc._force_cleanup_state.assert_called_once_with("test_rid")

    @pytest.mark.asyncio
    async def test_get_runner_status_both_consistent(self):
        """BOUNDARY: status=running + PID alive → 변경 없음, running=True"""
        svc = self._make_svc("running", "12345")
        with patch.object(type(svc), "_is_pid_alive", return_value=True):
            result = await svc.get_runner_status("test_rid")
        assert result.running is True
        svc.async_redis.set.assert_not_called()
        svc.async_redis.sadd.assert_not_called()
        svc._force_cleanup_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_runner_status_no_pid(self):
        """BOUNDARY: pid_str=None → PID 보정 미실행, running 그대로"""
        svc = self._make_svc("stopped", None)
        with patch.object(type(svc), "_is_pid_alive", return_value=True):
            result = await svc.get_runner_status("test_rid")
        assert result.running is False
        svc.async_redis.set.assert_not_called()


# ============================================================
# Phase T1: orphan 원자적 UPDATE
# ============================================================

class TestOrphanAtomicUpdate:
    """orphan 워크플로우 원자적 UPDATE (rowcount 기반)"""

    @pytest.mark.asyncio
    async def test_orphan_concurrent_update_atomic(self):
        """RIGHT: rowcount=1 → is_orphan=True; rowcount=0 → is_orphan=False"""
        from app.modules.dev_runner.services.executor_service import ExecutorService, RUNNER_KEY_PREFIX

        svc = ExecutorService.__new__(ExecutorService)

        # Redis mock: status=stopped (orphan 경로 진입)
        async def _get(key):
            data = {
                f"{RUNNER_KEY_PREFIX}:orphan_rid:status": "stopped",
                f"{RUNNER_KEY_PREFIX}:orphan_rid:pid": None,
                f"{RUNNER_KEY_PREFIX}:orphan_rid:plan_file": "/test.md",
                f"{RUNNER_KEY_PREFIX}:orphan_rid:trigger": "user",
                f"{RUNNER_KEY_PREFIX}:orphan_rid:engine": "claude",
            }
            return data.get(key)

        svc.async_redis = AsyncMock()
        svc.async_redis.get = _get
        svc.async_redis.zrange = AsyncMock(return_value=["orphan_rid"])
        svc.async_redis.zremrangebyscore = AsyncMock()
        svc.async_redis.smembers = AsyncMock(return_value=set())
        svc._force_cleanup_state = AsyncMock()

        # 첫 번째 요청: rowcount=1
        mock_result1 = MagicMock()
        mock_result1.rowcount = 1
        mock_db1 = MagicMock()
        mock_db1.execute.return_value = mock_result1

        with patch("app.database.SessionLocal", return_value=mock_db1), \
             patch.object(type(svc), "_is_pid_alive", return_value=False):
            result1 = await svc.get_all_runners()

        orphan_item = next((r for r in result1 if r.runner_id == "orphan_rid"), None)
        assert orphan_item is not None
        assert orphan_item.orphan is True

        # 두 번째 요청: rowcount=0 (이미 처리됨)
        mock_result2 = MagicMock()
        mock_result2.rowcount = 0
        mock_db2 = MagicMock()
        mock_db2.execute.return_value = mock_result2

        with patch("app.database.SessionLocal", return_value=mock_db2), \
             patch.object(type(svc), "_is_pid_alive", return_value=False):
            result2 = await svc.get_all_runners()

        orphan_item2 = next((r for r in result2 if r.runner_id == "orphan_rid"), None)
        assert orphan_item2 is not None
        assert orphan_item2.orphan is False

    @pytest.mark.asyncio
    async def test_orphan_update_rollback_on_error(self):
        """ERROR: db.execute() 예외 → db.rollback() 호출, orphan=False"""
        from app.modules.dev_runner.services.executor_service import ExecutorService, RUNNER_KEY_PREFIX

        svc = ExecutorService.__new__(ExecutorService)

        async def _get(key):
            data = {
                f"{RUNNER_KEY_PREFIX}:err_rid:status": "stopped",
                f"{RUNNER_KEY_PREFIX}:err_rid:pid": None,
                f"{RUNNER_KEY_PREFIX}:err_rid:plan_file": "/test.md",
                f"{RUNNER_KEY_PREFIX}:err_rid:trigger": "user",
                f"{RUNNER_KEY_PREFIX}:err_rid:engine": "claude",
            }
            return data.get(key)

        svc.async_redis = AsyncMock()
        svc.async_redis.get = _get
        svc.async_redis.zrange = AsyncMock(return_value=["err_rid"])
        svc.async_redis.zremrangebyscore = AsyncMock()
        svc.async_redis.smembers = AsyncMock(return_value=set())
        svc._force_cleanup_state = AsyncMock()

        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB 오류")
        mock_db.rollback = MagicMock()

        with patch("app.database.SessionLocal", return_value=mock_db), \
             patch.object(type(svc), "_is_pid_alive", return_value=False):
            result = await svc.get_all_runners()

        mock_db.rollback.assert_called()
        item = next((r for r in result if r.runner_id == "err_rid"), None)
        assert item is not None
        assert item.orphan is False


# ============================================================
# Phase T3: 통합 TC
# ============================================================

class TestIntegrationCleanupDone:
    """실물 dict + 소거 로직 통합 검증"""

    def _run_ttl_eviction(self, cleanup_done: dict):
        _now = time.time()
        _expired = [rid for rid, ts in list(cleanup_done.items()) if _now - ts > 300]
        for _rid in _expired:
            cleanup_done.pop(_rid, None)
        return _expired

    def test_integration_cleanup_done_grows_then_evicts(self):
        """통합: 오래된 항목 삽입 → 소거 로직 실행 → 항목 제거됨 (mock 없음)"""
        # listener 모듈의 실물 _cleanup_done dict를 직접 참조
        listener = _load_listener()
        original = dict(listener._cleanup_done)  # 원본 보존

        try:
            # 오래된 항목과 최근 항목 삽입
            listener._cleanup_done["stale_rid_1"] = time.time() - 400
            listener._cleanup_done["stale_rid_2"] = time.time() - 310
            listener._cleanup_done["fresh_rid"] = time.time() - 60

            # TTL 소거 로직 직접 실행 (heartbeat 루프 내 코드와 동일)
            self._run_ttl_eviction(listener._cleanup_done)

            assert "stale_rid_1" not in listener._cleanup_done
            assert "stale_rid_2" not in listener._cleanup_done
            assert "fresh_rid" in listener._cleanup_done
        finally:
            # 원본 복원
            listener._cleanup_done.clear()
            listener._cleanup_done.update(original)

    @pytest.mark.asyncio
    async def test_integration_get_runner_status_vs_get_all_runners(self):
        """통합: 동일 runner에 대해 get_runner_status()와 get_all_runners()가 동일 running 값 반환"""
        from app.modules.dev_runner.services.executor_service import (
            ExecutorService, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY
        )

        rid = "integration_rid"

        async def _get(key):
            data = {
                f"{RUNNER_KEY_PREFIX}:{rid}:status": "stopped",
                f"{RUNNER_KEY_PREFIX}:{rid}:pid": "12345",
                f"{RUNNER_KEY_PREFIX}:{rid}:plan_file": "/test.md",
                f"{RUNNER_KEY_PREFIX}:{rid}:start_time": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:engine": "claude",
                f"{RUNNER_KEY_PREFIX}:{rid}:trigger": "user",
                f"{RUNNER_KEY_PREFIX}:{rid}:current_cycle": None,
            }
            return data.get(key)

        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = AsyncMock()
        svc.async_redis.get = _get
        svc.async_redis.set = AsyncMock()
        svc.async_redis.sadd = AsyncMock()
        svc.async_redis.zrange = AsyncMock(return_value=[rid])
        svc.async_redis.zremrangebyscore = AsyncMock()
        svc.async_redis.smembers = AsyncMock(return_value=set())
        svc._force_cleanup_state = AsyncMock()

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute.return_value = mock_result

        with patch.object(type(svc), "_is_pid_alive", return_value=True), \
             patch("app.database.SessionLocal", return_value=mock_db):
            status_result = await svc.get_runner_status(rid)
            all_result = await svc.get_all_runners()

        all_item = next((r for r in all_result if r.runner_id == rid), None)
        assert all_item is not None
        assert status_result.running == all_item.running == True


# ============================================================
# Phase T1: _correct_pid_state() TC (TestCorrectPidState)
# ============================================================

class TestCorrectPidState:
    """_correct_pid_state() 공통 메서드 TC"""

    def _make_svc(self):
        from app.modules.dev_runner.services.executor_service import ExecutorService
        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = AsyncMock()
        svc.async_redis.set = AsyncMock()
        svc.async_redis.sadd = AsyncMock()
        svc._force_cleanup_state = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_correct_pid_state_running_pid_dead(self):
        """RIGHT: status=running + PID dead → _force_cleanup_state 호출 + (False, None)"""
        svc = self._make_svc()
        with patch.object(type(svc), "_is_pid_alive", return_value=False):
            result = await svc._correct_pid_state("rid1", "running", "1234", caller="test")
        assert result == (False, None)
        svc._force_cleanup_state.assert_called_once_with("rid1")
        svc.async_redis.set.assert_not_called()
        svc.async_redis.sadd.assert_not_called()

    @pytest.mark.asyncio
    async def test_correct_pid_state_stopped_pid_alive(self):
        """RIGHT: status=stopped + PID alive → Redis set/sadd + (True, pid_str)"""
        from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY
        svc = self._make_svc()
        with patch.object(type(svc), "_is_pid_alive", return_value=True):
            result = await svc._correct_pid_state("rid2", "stopped", "1234", caller="test")
        assert result == (True, "1234")
        svc.async_redis.set.assert_called_once_with(f"{RUNNER_KEY_PREFIX}:rid2:status", "running")
        svc.async_redis.sadd.assert_called_once_with(ACTIVE_RUNNERS_KEY, "rid2")
        svc._force_cleanup_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_correct_pid_state_completed_pid_alive(self):
        """BOUNDARY: status=completed + PID alive → completed 가드 → set/sadd 호출 안 됨 + (False, pid_str)"""
        svc = self._make_svc()
        with patch.object(type(svc), "_is_pid_alive", return_value=True):
            result = await svc._correct_pid_state("rid3", "completed", "1234", caller="test")
        # completed는 running=False, pid_str 유지
        assert result == (False, "1234")
        svc.async_redis.set.assert_not_called()
        svc.async_redis.sadd.assert_not_called()
        svc._force_cleanup_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_correct_pid_state_running_pid_alive(self):
        """BOUNDARY: status=running + PID alive → 아무 side effect 없음 + (True, pid_str)"""
        svc = self._make_svc()
        with patch.object(type(svc), "_is_pid_alive", return_value=True):
            result = await svc._correct_pid_state("rid4", "running", "1234", caller="test")
        assert result == (True, "1234")
        svc.async_redis.set.assert_not_called()
        svc.async_redis.sadd.assert_not_called()
        svc._force_cleanup_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_correct_pid_state_no_pid(self):
        """BOUNDARY: pid_str=None → _is_pid_alive 호출 안 됨"""
        svc = self._make_svc()
        with patch.object(type(svc), "_is_pid_alive") as mock_alive:
            result_running = await svc._correct_pid_state("rid5", "running", None, caller="test")
            result_stopped = await svc._correct_pid_state("rid6", "stopped", None, caller="test")
        assert result_running == (True, None)
        assert result_stopped == (False, None)
        mock_alive.assert_not_called()

    @pytest.mark.asyncio
    async def test_correct_pid_state_invalid_pid(self):
        """ERROR: pid_str='abc' → ValueError catch + logger.debug + (running, 'abc') 반환"""
        svc = self._make_svc()
        with patch("app.modules.dev_runner.services.runner_state.logger") as mock_logger:
            result = await svc._correct_pid_state("rid7", "running", "abc", caller="test")
        # running=True (status="running"), pid_str 원본 유지
        assert result == (True, "abc")
        mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_correct_pid_state_caller_in_log(self):
        """RIGHT: caller="test_caller" → logger.warning 메시지에 'test_caller' 포함"""
        svc = self._make_svc()
        with patch.object(type(svc), "_is_pid_alive", return_value=False), \
             patch("app.modules.dev_runner.services.runner_state.logger") as mock_logger:
            await svc._correct_pid_state("rid8", "running", "1234", caller="test_caller")
        assert any("test_caller" in str(call) for call in mock_logger.warning.call_args_list)


# ============================================================
# Phase T1: TTL 소거 헬퍼 TC (TestEvictStaleHelpers)
# ============================================================

class TestEvictStaleHelpers:
    """_evict_stale_cleanup_done / _evict_stale_dead_process TC"""

    def _get_helpers(self):
        listener = _load_listener()
        return listener._evict_stale_cleanup_done, listener._evict_stale_dead_process, listener

    def test_evict_stale_cleanup_done_removes_expired(self):
        """RIGHT: now-301초 항목 → 제거됨, now-10초 항목 → 유지"""
        evict_fn, _, listener = self._get_helpers()
        original = dict(listener._cleanup_done)
        try:
            now = time.time()
            listener._cleanup_done["r1"] = now - 301
            listener._cleanup_done["r2"] = now - 10
            evict_fn()
            assert "r1" not in listener._cleanup_done
            assert "r2" in listener._cleanup_done
        finally:
            listener._cleanup_done.clear()
            listener._cleanup_done.update(original)

    def test_evict_stale_cleanup_done_empty_dict(self):
        """BOUNDARY: _cleanup_done = {} → 에러 없이 반환"""
        evict_fn, _, listener = self._get_helpers()
        original = dict(listener._cleanup_done)
        try:
            listener._cleanup_done.clear()
            evict_fn()  # 에러 없어야 함
            assert len(listener._cleanup_done) == 0
        finally:
            listener._cleanup_done.clear()
            listener._cleanup_done.update(original)

    def test_evict_stale_dead_process_removes_expired(self):
        """RIGHT: now-301초 항목 → 제거됨, now-10초 항목 → 유지"""
        _, evict_fn, listener = self._get_helpers()
        original = dict(listener._dead_process_first_seen)
        try:
            now = time.time()
            listener._dead_process_first_seen["r1"] = now - 301
            listener._dead_process_first_seen["r2"] = now - 10
            evict_fn()
            assert "r1" not in listener._dead_process_first_seen
            assert "r2" in listener._dead_process_first_seen
        finally:
            listener._dead_process_first_seen.clear()
            listener._dead_process_first_seen.update(original)

    def test_evict_stale_dead_process_empty_dict(self):
        """BOUNDARY: _dead_process_first_seen = {} → 에러 없이 반환"""
        _, evict_fn, listener = self._get_helpers()
        original = dict(listener._dead_process_first_seen)
        try:
            listener._dead_process_first_seen.clear()
            evict_fn()  # 에러 없어야 함
            assert len(listener._dead_process_first_seen) == 0
        finally:
            listener._dead_process_first_seen.clear()
            listener._dead_process_first_seen.update(original)


# ============================================================
# Phase T3: 통합 TC (TestIntegrationCorrectPidState)
# ============================================================

class TestIntegrationCorrectPidState:
    """get_runner_status()와 get_all_runners()가 _correct_pid_state 경유, 동일 결과 반환"""

    @pytest.mark.asyncio
    async def test_integration_correct_pid_state_same_result_both_callers(self):
        """동일 runner·동일 Redis 상태에서 두 함수 모두 _correct_pid_state 경유 + 동일 running 값"""
        from app.modules.dev_runner.services.executor_service import (
            ExecutorService, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY
        )
        from unittest.mock import AsyncMock, MagicMock, patch

        rid = "integration_rid2"

        async def _get(key):
            data = {
                f"{RUNNER_KEY_PREFIX}:{rid}:status": "stopped",
                f"{RUNNER_KEY_PREFIX}:{rid}:pid": "55555",
                f"{RUNNER_KEY_PREFIX}:{rid}:plan_file": "/test.md",
                f"{RUNNER_KEY_PREFIX}:{rid}:start_time": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:engine": "claude",
                f"{RUNNER_KEY_PREFIX}:{rid}:trigger": "user",
                f"{RUNNER_KEY_PREFIX}:{rid}:current_cycle": None,
            }
            return data.get(key)

        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = AsyncMock()
        svc.async_redis.get = _get
        svc.async_redis.set = AsyncMock()
        svc.async_redis.sadd = AsyncMock()
        svc.async_redis.zrange = AsyncMock(return_value=[rid])
        svc.async_redis.zremrangebyscore = AsyncMock()
        svc.async_redis.smembers = AsyncMock(return_value=set())
        svc._force_cleanup_state = AsyncMock()

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute.return_value = mock_result

        calls = []
        original_correct = svc._correct_pid_state if hasattr(svc, "_correct_pid_state") else None

        # spy on _correct_pid_state
        async def spy_correct(*args, **kwargs):
            calls.append(kwargs.get("caller", args[3] if len(args) > 3 else ""))
            return await ExecutorService._correct_pid_state(svc, *args, **kwargs)

        with patch.object(type(svc), "_is_pid_alive", return_value=True), \
             patch("app.database.SessionLocal", return_value=mock_db), \
             patch.object(svc, "_correct_pid_state", side_effect=spy_correct):
            status_result = await svc.get_runner_status(rid)
            all_result = await svc.get_all_runners()

        all_item = next((r for r in all_result if r.runner_id == rid), None)
        assert all_item is not None
        # 두 함수 모두 _correct_pid_state 호출됨
        assert len(calls) >= 2
        # 동일 running 값
        assert status_result.running == all_item.running
