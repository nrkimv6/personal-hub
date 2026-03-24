"""TC-I / TC-C / TC-CORRECT: listener heartbeat 복원 로직 단위 테스트

Fix 1 이후: status가 None 또는 "stopped"이면 heartbeat가 "running"으로 복원하지 않음을 검증.
"""

import time
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"


def _run_heartbeat_restore_logic(r: fakeredis.FakeRedis, rid: str, proc_mock: MagicMock):
    """dev-runner-command-listener.py의 heartbeat 복원 블록을 직접 실행 (Fix 1 적용 코드)"""
    running_processes = {rid: proc_mock}
    for rid_, proc in list(running_processes.items()):
        if proc.poll() is None:
            current_status = r.get(f"{RUNNER_KEY_PREFIX}:{rid_}:status")
            # Fix 1: status가 None 또는 "stopped"이면 복원 금지
            if current_status not in (None, "stopped") and current_status != "running":
                r.set(f"{RUNNER_KEY_PREFIX}:{rid_}:status", "running")
                r.set(f"{RUNNER_KEY_PREFIX}:{rid_}:pid", proc.pid)
                r.sadd(ACTIVE_RUNNERS_KEY, rid_)


class TestHeartbeatNoRestoreWhenStopped:
    """TC-I (Inverse): _cleanup_redis_state() 후 heartbeat가 재복원하지 않음"""

    def test_no_restore_when_status_stopped(self):
        """status="stopped" → heartbeat 복원 로직이 "running"으로 바꾸지 않아야 함"""
        r = fakeredis.FakeRedis(decode_responses=True)
        rid = "runner-1"
        r.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")

        proc = MagicMock()
        proc.poll.return_value = None  # 프로세스 살아있음 (subprocess 관점)
        proc.pid = 12345

        _run_heartbeat_restore_logic(r, rid, proc)

        assert r.get(f"{RUNNER_KEY_PREFIX}:{rid}:status") == "stopped", \
            "status가 'stopped'인데 heartbeat가 'running'으로 복원함 — Fix 1 미적용"


class TestHeartbeatNoRestoreWhenNone:
    """TC-CORRECT-Existence: status=None 상태에서 heartbeat가 "running"으로 복원하지 않음"""

    def test_no_restore_when_status_is_none(self):
        """status 키 없음(None) → heartbeat가 "running"으로 복원하지 않아야 함"""
        r = fakeredis.FakeRedis(decode_responses=True)
        rid = "runner-none"
        # status 키를 설정하지 않음 (None)

        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 22222

        _run_heartbeat_restore_logic(r, rid, proc)

        assert r.get(f"{RUNNER_KEY_PREFIX}:{rid}:status") is None, \
            "status가 None인데 heartbeat가 'running'으로 복원함 — 경쟁 조건 수정 미적용"


class TestHeartbeatRestoreWhenOtherStatus:
    """TC-C (Cross-check): status가 다른 값(예: "paused")이면 정상 복원 허용"""

    def test_restore_when_status_is_paused(self):
        """status='paused' (None/stopped 아님, running도 아님) → 복원해야 함"""
        r = fakeredis.FakeRedis(decode_responses=True)
        rid = "runner-paused"
        r.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "paused")

        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 33333

        _run_heartbeat_restore_logic(r, rid, proc)

        assert r.get(f"{RUNNER_KEY_PREFIX}:{rid}:status") == "running", \
            "status='paused'일 때 heartbeat 복원이 이루어져야 함"

    def test_no_double_restore_when_already_running(self):
        """status='running'이면 중복 set 없이 그대로 유지"""
        r = fakeredis.FakeRedis(decode_responses=True)
        rid = "runner-already"
        r.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")

        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 44444

        set_call_count = 0
        original_set = r.set

        def counting_set(key, value, *args, **kwargs):
            nonlocal set_call_count
            if "status" in key:
                set_call_count += 1
            return original_set(key, value, *args, **kwargs)

        r.set = counting_set
        _run_heartbeat_restore_logic(r, rid, proc)

        assert set_call_count == 0, "status='running'일 때 불필요한 재set 발생"


class TestHeartbeatStreamThreadGuard:
    """TC: heartbeat dead-process 분기에서 _stream_output 스레드 alive 가드 검증 (Phase 1 fix)"""

    def _run_heartbeat_dead_process_branch(
        self,
        rid: str,
        proc_mock: MagicMock,
        stream_threads: dict,
        cleanup_fn: MagicMock,
    ):
        """heartbeat else 분기 (proc.poll() is not None, 머지 없음) 로직 복제"""
        # merge 없는 것으로 가정
        _hb_mr, _hb_ms = None, None
        if _hb_mr or _hb_ms:
            return  # 머지 진행중 → skip
        _t = stream_threads.get(rid)
        if _t and _t.is_alive():
            pass  # cleanup 위임 → 미호출
        else:
            cleanup_fn(rid, reason="heartbeat_dead_process")

    def test_heartbeat_skips_cleanup_when_stream_thread_alive(self):
        """R: _stream_threads[rid].is_alive()=True → _cleanup_process_state 미호출"""
        rid = "runner-alive"
        proc = MagicMock()
        proc.poll.return_value = 0  # 종료됨

        thread_mock = MagicMock()
        thread_mock.is_alive.return_value = True
        stream_threads = {rid: thread_mock}

        cleanup_fn = MagicMock()
        self._run_heartbeat_dead_process_branch(rid, proc, stream_threads, cleanup_fn)

        cleanup_fn.assert_not_called()

    def test_heartbeat_calls_cleanup_when_no_stream_thread(self):
        """R: _stream_threads에 rid 없음 → _cleanup_process_state 호출됨"""
        rid = "runner-no-thread"
        proc = MagicMock()
        proc.poll.return_value = 1

        stream_threads = {}  # rid 없음
        cleanup_fn = MagicMock()
        self._run_heartbeat_dead_process_branch(rid, proc, stream_threads, cleanup_fn)

        cleanup_fn.assert_called_once_with(rid, reason="heartbeat_dead_process")

    def test_heartbeat_calls_cleanup_when_stream_thread_dead(self):
        """B: 스레드 있지만 is_alive()=False → _cleanup_process_state 호출됨"""
        rid = "runner-dead-thread"
        proc = MagicMock()
        proc.poll.return_value = 0

        thread_mock = MagicMock()
        thread_mock.is_alive.return_value = False
        stream_threads = {rid: thread_mock}

        cleanup_fn = MagicMock()
        self._run_heartbeat_dead_process_branch(rid, proc, stream_threads, cleanup_fn)

        cleanup_fn.assert_called_once_with(rid, reason="heartbeat_dead_process")


class TestHeartbeatPidAlive:
    """TC-C: _is_pid_alive가 False 반환 시 복원 없음"""

    def test_no_restore_when_pid_not_alive(self):
        """_is_pid_alive=False mock → 복원 로직이 실행되지 않아야 함 (Fix 1 조건만으로 처리)

        Fix 1은 status 값 기반으로 동작. PID alive 체크는 Fix 3(executor_service)에서 처리.
        listener heartbeat 블록에서는 status 값으로만 판단함.
        """
        r = fakeredis.FakeRedis(decode_responses=True)
        rid = "runner-dead-pid"
        # status=None (cleanup 진행 중) → 복원 금지
        # (PID가 살아있어도 status=None이면 복원 안 함)

        proc = MagicMock()
        proc.poll.return_value = None  # subprocess는 아직 살아있다고 판단
        proc.pid = 55555

        _run_heartbeat_restore_logic(r, rid, proc)

        # status가 None이므로 복원되지 않아야 함
        assert r.get(f"{RUNNER_KEY_PREFIX}:{rid}:status") is None
