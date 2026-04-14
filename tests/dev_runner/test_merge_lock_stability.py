"""
merge-lock 안정성 강화 TC

Phase T1 (단위):
- test_release_merge_lock_lua_uses_eval: Lua eval 경로 검증
- test_release_merge_lock_lua_owner_match_returns_true: eval=1 → True
- test_release_merge_lock_lua_owner_mismatch_returns_false: eval=0 → False
- test_acquire_enqueue_lua_no_duplicate: 중복 등록 방지
- test_acquire_enqueue_lua_new_entry: 신규 등록
- test_acquire_stale_front_dead_pid_removed: 죽은 PID → LREM
- test_acquire_stale_front_no_pid_key_removed: PID 없음+status None → LREM
- test_cleanup_process_state_lrem_queue: cleanup 시 큐 LREM
- test_execute_merge_with_lock_success: 헬퍼 exit_code=0 → merged
- test_execute_merge_with_lock_conflict: 헬퍼 exit_code=3 → conflict
- test_execute_merge_with_lock_acquire_fail: acquire 실패 → error, release 미호출

Phase T3 (E2E):
- test_release_race_two_runners_e2e: 두 runner race, 소유자만 해제
- test_stale_front_recovery_e2e: 죽은 front → 제거 → 다음 runner 획득
"""
import os
import sys
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

SCRIPTS_DIR = Path(__file__).parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
_PLAN_RUNNER_DIR = SCRIPTS_DIR / "plan_runner"
if str(_PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_PLAN_RUNNER_DIR))

# merge_lock 모듈 직접 import
import merge_lock as ml

# dev-runner-command-listener 동적 로딩
_listener_spec = importlib.util.spec_from_file_location(
    "dev_runner_command_listener",
    _PLAN_RUNNER_DIR / "dev-runner-command-listener.py",
)
listener = importlib.util.module_from_spec(_listener_spec)
_listener_spec.loader.exec_module(listener)

pytestmark = pytest.mark.skip(reason="merge_lock deprecated — merge_queue로 대체")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis() -> MagicMock:
    r = MagicMock()
    r.eval.return_value = 1
    r.get.return_value = None
    r.set.return_value = True
    r.delete.return_value = 1
    r.lrange.return_value = []
    r.lindex.return_value = None
    r.lrem.return_value = 1
    r.lpush.return_value = 1
    r.expire.return_value = True
    r.publish.return_value = 0
    r.srem.return_value = 1
    r.zadd.return_value = 1
    return r


def _patch_subprocess(exit_code: int = 0):
    proc = MagicMock()
    proc.returncode = exit_code
    return patch("subprocess.run", return_value=proc)


# ---------------------------------------------------------------------------
# Phase T1: release_merge_lock Lua 원자화
# ---------------------------------------------------------------------------

class TestReleaseMergeLockLua:

    def test_release_merge_lock_lua_uses_eval(self):
        """R(정상): release_merge_lock 호출 시 redis.eval을 사용하고 get/delete는 미호출"""
        r = _make_redis()
        r.eval.return_value = 1

        result = ml.release_merge_lock(r, "runner-A")

        r.eval.assert_called_once_with(ml._RELEASE_LUA, 1, ml.MERGE_LOCK_KEY, "runner-A")
        r.get.assert_not_called()
        r.delete.assert_not_called()
        assert result is True

    def test_release_merge_lock_lua_owner_match_returns_true(self):
        """R(정상): eval 반환값 1 → release_merge_lock() True 반환"""
        r = _make_redis()
        r.eval.return_value = 1

        assert ml.release_merge_lock(r, "runner-A") is True

    def test_release_merge_lock_lua_owner_mismatch_returns_false(self):
        """B(경계): eval 반환값 0 → release_merge_lock() False 반환 (소유자 불일치 또는 만료)"""
        r = _make_redis()
        r.eval.return_value = 0

        assert ml.release_merge_lock(r, "runner-B") is False
        r.delete.assert_not_called()


# ---------------------------------------------------------------------------
# Phase T1: acquire_merge_lock 큐 등록 Lua 원자화
# ---------------------------------------------------------------------------

class TestAcquireEnqueueLua:

    def test_acquire_enqueue_lua_new_entry(self):
        """R(정상): 큐에 없는 runner_id → _ENQUEUE_LUA eval 반환값 1 (등록됨)"""
        r = _make_redis()
        r.eval.return_value = 1   # 새로 등록
        # lindex가 runner_id를 즉시 반환 → lock 획득 성공
        r.lindex.return_value = "runner-X"
        r.set.return_value = True  # SETNX 성공

        result = ml.acquire_merge_lock(r, "runner-X", timeout=1, lock_ttl=1)

        # eval(_ENQUEUE_LUA, ...) 호출 검증
        enqueue_calls = [c for c in r.eval.call_args_list if c.args[0] == ml._ENQUEUE_LUA]
        assert len(enqueue_calls) == 1
        assert result is True

    def test_acquire_enqueue_lua_no_duplicate(self):
        """B(경계): 이미 큐에 있는 runner_id → eval 반환값 0, RPUSH 미발생"""
        r = _make_redis()
        r.eval.return_value = 0   # 이미 존재

        # 짧은 timeout으로 폴링 없이 바로 만료
        r.lindex.return_value = "other-runner"  # 다른 runner가 앞에 있음
        ml.acquire_merge_lock(r, "runner-X", timeout=0, lock_ttl=1)

        enqueue_calls = [c for c in r.eval.call_args_list if c.args[0] == ml._ENQUEUE_LUA]
        assert len(enqueue_calls) == 1
        r.rpush.assert_not_called()  # Lua가 처리하므로 rpush 직접 호출 없음


# ---------------------------------------------------------------------------
# Phase T1: stale front runner 감지
# ---------------------------------------------------------------------------

class TestStaleFrontRemoval:

    def test_acquire_stale_front_dead_pid_removed(self):
        """B(경계): 큐 맨 앞 runner의 PID가 죽은 프로세스 → LREM 호출"""
        r = _make_redis()
        r.eval.return_value = 1  # enqueue 성공

        dead_pid = 99999
        # front = "dead-runner", pid = dead_pid
        def _get(key):
            if "dead-runner:pid" in key:
                return str(dead_pid)
            return None
        r.get.side_effect = _get
        # lindex: 처음엔 dead-runner, 이후 my-runner(내 차례)
        r.lindex.side_effect = ["dead-runner", "my-runner"]
        r.set.return_value = True  # lock SETNX 성공

        with patch("os.kill", side_effect=ProcessLookupError("dead")):
            ml.acquire_merge_lock(r, "my-runner", timeout=2, lock_ttl=1)

        # LREM으로 dead-runner 제거 확인
        lrem_calls = r.lrem.call_args_list
        removed = any(c.args[2] == "dead-runner" for c in lrem_calls)
        assert removed, f"dead-runner가 LREM으로 제거되어야 함. lrem calls: {lrem_calls}"

    def test_acquire_stale_front_no_pid_key_removed(self):
        """B(경계): 큐 맨 앞 runner의 PID 키가 없고 status도 None → stale 판정, LREM"""
        r = _make_redis()
        r.eval.return_value = 1
        # lindex: 처음엔 ghost-runner, 이후 my-runner
        r.lindex.side_effect = ["ghost-runner", "my-runner"]
        r.set.return_value = True
        # pid 키 없음, status 키도 없음 (r.get returns None by default)

        ml.acquire_merge_lock(r, "my-runner", timeout=2, lock_ttl=1)

        lrem_calls = r.lrem.call_args_list
        removed = any(c.args[2] == "ghost-runner" for c in lrem_calls)
        assert removed, f"ghost-runner가 LREM으로 제거되어야 함. lrem calls: {lrem_calls}"


# ---------------------------------------------------------------------------
# Phase T1: cleanup + get_status 큐 LREM
# ---------------------------------------------------------------------------

class TestCleanupQueueLrem:

    def test_cleanup_process_state_lrem_queue(self):
        """R(정상): _cleanup_process_state() 호출 시 merge-wait-queue에서 LREM"""
        r = _make_redis()
        runner_id = "runner-cleanup-01"

        with patch.object(listener, "_wf_manager", None), \
             patch.object(listener, "WorktreeManager") as mock_wt, \
             patch.object(listener, "_is_plan_in_progress", return_value=False):
            listener._cleanup_process_state(runner_id, r)

        # lrem("plan-runner:merge-wait-queue", 0, runner_id) 호출 확인
        lrem_calls = r.lrem.call_args_list
        queue_removed = any(
            len(c.args) >= 3 and c.args[0] == "plan-runner:merge-wait-queue"
            and c.args[2] == runner_id
            for c in lrem_calls
        )
        assert queue_removed, f"cleanup 시 merge-wait-queue LREM 미호출. calls: {lrem_calls}"


# ---------------------------------------------------------------------------
# Phase T1: _execute_merge_with_lock 헬퍼
# ---------------------------------------------------------------------------

class TestExecuteMergeWithLock:

    def test_execute_merge_with_lock_success(self):
        """R(정상): exit_code=0 → {"success": True, "merge_status": "merged"}, release 1회"""
        r = _make_redis()

        with patch("merge_lock.acquire_merge_lock", return_value=True) as mock_acq, \
             patch("merge_lock.release_merge_lock") as mock_rel, \
             _patch_subprocess(exit_code=0):
            result = listener._execute_merge_with_lock("runner-01", r)

        assert result["success"] is True
        assert result["merge_status"] == "merged"
        mock_rel.assert_called_once()

    def test_execute_merge_with_lock_conflict(self):
        """B(경계): exit_code=3 → {"success": False, "merge_status": "conflict"}, release 1회"""
        r = _make_redis()

        with patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock") as mock_rel, \
             _patch_subprocess(exit_code=3):
            result = listener._execute_merge_with_lock("runner-02", r)

        assert result["success"] is False
        assert result["merge_status"] == "conflict"
        mock_rel.assert_called_once()

    def test_execute_merge_with_lock_acquire_fail(self):
        """E(에러): acquire 실패 → {"success": False, "merge_status": "error"}, release 미호출"""
        r = _make_redis()

        with patch("merge_lock.acquire_merge_lock", return_value=False), \
             patch("merge_lock.release_merge_lock") as mock_rel:
            result = listener._execute_merge_with_lock("runner-03", r)

        assert result["success"] is False
        assert result["merge_status"] == "error"
        mock_rel.assert_not_called()


# ---------------------------------------------------------------------------
# Phase T3: E2E 검증 (fakeredis 사용)
# ---------------------------------------------------------------------------

class TestMergeLockStabilityE2E:
    """
    E2E 검증 — fakeredis가 Lua eval을 지원하지 않으므로 MagicMock으로 Lua 동작을 시뮬레이션.

    _RELEASE_LUA 시뮬레이션: eval(script, 1, key, runner_id) → owner 일치 시 1, 불일치 시 0
    _ENQUEUE_LUA 시뮬레이션: eval(script, 1, queue_key, runner_id) → 신규 등록 시 1, 이미 존재 시 0
    """

    def test_release_race_two_runners_e2e(self):
        """runner-A 소유 lock → runner-B release 시도 → 0(실패). runner-A release → 1(성공)"""
        # lock 상태: "runner-A"가 보유
        lock_store = {"value": "runner-A"}

        def _eval(script, num_keys, key, runner_id):
            """_RELEASE_LUA 동작: 현재 소유자와 runner_id 비교 후 DEL"""
            if script == ml._RELEASE_LUA:
                if lock_store["value"] == runner_id:
                    lock_store["value"] = None
                    return 1
                return 0
            return 0

        r = MagicMock()
        r.eval.side_effect = _eval

        # runner-B release 시도 → 실패 (소유자 불일치)
        result_b = ml.release_merge_lock(r, "runner-B")
        assert result_b is False
        assert lock_store["value"] == "runner-A"  # lock 유지

        # runner-A release → 성공
        result_a = ml.release_merge_lock(r, "runner-A")
        assert result_a is True
        assert lock_store["value"] is None  # lock 해제

    def test_stale_front_recovery_e2e(self):
        """큐: [dead-runner, my-runner] → os.kill mock으로 dead 판정 → my-runner가 lock 획득"""
        # 큐 상태 시뮬레이션
        queue = ["dead-runner", "my-runner"]
        pid_store = {"dead-runner": "99999"}
        lock_store = {"value": None}

        def _eval(script, num_keys, key, runner_id):
            if script == ml._ENQUEUE_LUA:
                if runner_id in queue:
                    return 0
                queue.append(runner_id)
                return 1
            return 0

        def _lindex(key, idx):
            return queue[idx] if queue else None

        def _lrem(key, count, value):
            if value in queue:
                queue.remove(value)
                return 1
            return 0

        def _set(key, value, nx=False, ex=None):
            if nx and lock_store["value"] is not None:
                return None
            lock_store["value"] = value
            return True

        def _get(key):
            for runner, pid in pid_store.items():
                if f":{runner}:pid" in key:
                    return pid
            return None

        def _expire(key, ttl):
            return True

        r = MagicMock()
        r.eval.side_effect = _eval
        r.lindex.side_effect = _lindex
        r.lrem.side_effect = _lrem
        r.set.side_effect = _set
        r.get.side_effect = _get
        r.expire.side_effect = _expire

        def _fake_kill(pid, sig):
            if pid == 99999:
                raise ProcessLookupError("dead")

        with patch("os.kill", side_effect=_fake_kill):
            result = ml.acquire_merge_lock(r, "my-runner", timeout=5, lock_ttl=5)

        assert result is True, "my-runner가 stale front 제거 후 lock을 획득해야 함"
        assert "dead-runner" not in queue, f"dead-runner가 큐에 남아있음: {queue}"
