"""
TC: _reconnect_surviving_runners — PID 없는 dm-* orphan runner의 merge_status 기반 분기
scripts/dev-runner-command-listener.py 버그 수정 검증
"""
import sys
import importlib
import importlib.util
import types
import threading
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "dev-runner-command-listener.py"

_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"


def _load_listener():
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location("_listener_reconnect", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


def _get_process_utils():
    return sys.modules["_dr_process_utils"]


def _reset_shared_state():
    state_mod = sys.modules["_dr_state"]
    state_mod.get_running_processes().clear()
    state_mod.get_running_log_files().clear()
    state_mod.get_stream_threads().clear()
    state_mod.get_cleanup_done().clear()
    state_mod.get_dead_process_first_seen().clear()
    state_mod.get_zombie_first_seen().clear()


def make_redis_for_reconnect(runner_id: str, pid: str | None, merge_status: str | None):
    """reconnect 테스트용 Redis mock — active_runners + runner 키 시뮬레이션"""
    redis = MagicMock()

    redis.smembers.return_value = {runner_id}

    def redis_get(key):
        if key == f"{RUNNER_KEY_PREFIX}:{runner_id}:pid":
            return pid
        if key == f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status":
            return merge_status
        if key == f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested":
            return None
        return None

    redis.get.side_effect = redis_get
    redis.set.return_value = True
    redis.lpush.return_value = 1
    redis.expire.return_value = True
    redis.scan_iter.return_value = iter([])  # orphan scan 없음
    return redis


# ---------------------------------------------------------------------------
# active_runners 루프: PID 없는 dm-* runner
# ---------------------------------------------------------------------------

class TestReconnectDmOrphan:
    def test_reconnect_dm_orphan_queued_calls_recover(self):
        """R(Right): active_runners에 dm-* runner, pid 없음, merge_status=queued → _recover_pending_merge 호출"""
        cl = _load_listener()
        pu = _get_process_utils()
        _reset_shared_state()
        runner_id = "t-reconn-abcd"
        redis = make_redis_for_reconnect(runner_id, pid=None, merge_status="queued")

        started_threads = []
        original_thread_init = threading.Thread.__init__

        def mock_thread_start(self_t):
            started_threads.append(self_t)

        with patch.object(pu, "_cleanup_process_state") as mock_cleanup, \
             patch.object(pu, "_recover_pending_merge") as mock_recover, \
             patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            cl._reconnect_surviving_runners(redis)

        # threading.Thread가 _recover_pending_merge를 target으로 생성됐는지 확인
        assert mock_thread_cls.called, "_recover_pending_merge 스레드 미생성"
        kwargs = mock_thread_cls.call_args[1]
        assert kwargs.get("target") is mock_recover, \
            f"스레드 target이 _recover_pending_merge가 아님: {kwargs.get('target')}"
        mock_cleanup.assert_not_called()

    def test_reconnect_dm_orphan_merging_calls_recover(self):
        """R(Right): merge_status=merging → _recover_pending_merge 호출"""
        cl = _load_listener()
        pu = _get_process_utils()
        _reset_shared_state()
        runner_id = "t-reconn-beef"
        redis = make_redis_for_reconnect(runner_id, pid=None, merge_status="merging")

        with patch.object(pu, "_cleanup_process_state") as mock_cleanup, \
             patch.object(pu, "_recover_pending_merge") as mock_recover, \
             patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            cl._reconnect_surviving_runners(redis)

        assert mock_thread_cls.called, "merging 상태인데 스레드 미생성"
        kwargs = mock_thread_cls.call_args[1]
        assert kwargs.get("target") is mock_recover
        mock_cleanup.assert_not_called()

    def test_reconnect_dm_orphan_no_merge_status_cleanup(self):
        """B(Boundary): pid 없음 + merge_status 없음 → cleanup 호출"""
        cl = _load_listener()
        pu = _get_process_utils()
        _reset_shared_state()
        runner_id = "t-reconn-dead"
        redis = make_redis_for_reconnect(runner_id, pid=None, merge_status=None)

        with patch.object(pu, "_cleanup_process_state") as mock_cleanup, \
             patch("threading.Thread") as mock_thread_cls:
            cl._reconnect_surviving_runners(redis)

        mock_cleanup.assert_called_once()
        mock_thread_cls.assert_not_called()


# ---------------------------------------------------------------------------
# orphan scan: PID 없는 고아 키
# ---------------------------------------------------------------------------

class TestReconnectOrphanScan:
    def _make_redis_orphan_scan(self, orphan_id: str, merge_status: str | None):
        """orphan scan 전용 Redis mock — active_runners 비어있고 scan_iter에서 고아 키 반환"""
        redis = MagicMock()
        redis.smembers.return_value = set()  # active_runners 비어있음

        status_key = f"{RUNNER_KEY_PREFIX}:{orphan_id}:status"
        redis.scan_iter.return_value = iter([status_key])

        def redis_get(key):
            if key == f"{RUNNER_KEY_PREFIX}:{orphan_id}:pid":
                return None
            if key == f"{RUNNER_KEY_PREFIX}:{orphan_id}:merge_status":
                return merge_status
            if key == f"{RUNNER_KEY_PREFIX}:{orphan_id}:merge_requested":
                return None
            return None

        redis.get.side_effect = redis_get
        redis.set.return_value = True
        return redis

    def test_reconnect_orphan_scan_no_pid_queued(self):
        """R(Right): orphan scan — dm-* pid 없음, merge_status=queued → _recover_pending_merge"""
        cl = _load_listener()
        pu = _get_process_utils()
        _reset_shared_state()
        orphan_id = "dm-cafe9999"
        redis = self._make_redis_orphan_scan(orphan_id, merge_status="queued")

        with patch.object(pu, "_cleanup_process_state") as mock_cleanup, \
             patch.object(pu, "_recover_pending_merge") as mock_recover, \
             patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            cl._reconnect_surviving_runners(redis)

        assert mock_thread_cls.called, "orphan scan queued 상태인데 스레드 미생성"
        kwargs = mock_thread_cls.call_args[1]
        assert kwargs.get("target") is mock_recover
        mock_cleanup.assert_not_called()

    def test_reconnect_orphan_scan_no_pid_cleanup(self):
        """B(Boundary): orphan scan — pid 없음, merge_status 없음 → cleanup"""
        cl = _load_listener()
        pu = _get_process_utils()
        _reset_shared_state()
        orphan_id = "dm-dead1111"
        redis = self._make_redis_orphan_scan(orphan_id, merge_status=None)

        with patch.object(pu, "_cleanup_process_state") as mock_cleanup, \
             patch("threading.Thread") as mock_thread_cls:
            cl._reconnect_surviving_runners(redis)

        mock_cleanup.assert_called()
        mock_thread_cls.assert_not_called()


# ──────────────────────────────────────────────
# stopped+user 보존 계약 TC (Phase 2-1)
# ──────────────────────────────────────────────

class TestReconnectStoppedUserPreservation:
    """_reconnect_surviving_runners() — stopped+user 러너 cleanup 스킵 보존 계약"""

    def _make_redis_stopped_user(self, runner_id: str, trigger: str):
        """stopped+trigger runner가 ACTIVE에 남아있는 상황 시뮬레이션"""
        redis = MagicMock()
        redis.smembers.return_value = {runner_id}

        def redis_get(key):
            if key == f"{RUNNER_KEY_PREFIX}:{runner_id}:status":
                return "stopped"
            if key == f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger":
                return trigger
            return None

        redis.get.side_effect = redis_get
        return redis

    def _make_redis_orphan_stopped_user(self, orphan_id: str, trigger: str):
        """orphan stopped+trigger runner (active_runners에 없음) 시뮬레이션"""
        redis = MagicMock()
        redis.smembers.return_value = set()  # active_runners에 없음

        def redis_get(key):
            if key == f"{RUNNER_KEY_PREFIX}:{orphan_id}:status":
                return "stopped"
            if key == f"{RUNNER_KEY_PREFIX}:{orphan_id}:trigger":
                return trigger
            return None

        redis.get.side_effect = redis_get

        # orphan scan: runners:*:status 키 스캔 결과 시뮬레이션
        redis.scan_iter.return_value = iter(
            [f"{RUNNER_KEY_PREFIX}:{orphan_id}:status"]
        )
        return redis

    def test_active_stopped_user_skips_cleanup(self):
        """R: active_runners에 있는 stopped+user 러너 → _cleanup_process_state 미호출"""
        cl = _load_listener()
        pu = _get_process_utils()
        _reset_shared_state()
        runner_id = "su-active-001"
        redis = self._make_redis_stopped_user(runner_id, trigger="user")

        with patch.object(pu, "_cleanup_process_state") as mock_cleanup:
            cl._reconnect_surviving_runners(redis)

        mock_cleanup.assert_not_called(), (
            "stopped+user runner가 cleanup됨. dismiss 전까지 보존되어야 한다."
        )

    def test_active_stopped_user_all_skips_cleanup(self):
        """R: active_runners에 있는 stopped+user:all 러너 → cleanup 스킵"""
        cl = _load_listener()
        pu = _get_process_utils()
        _reset_shared_state()
        runner_id = "su-all-active-002"
        redis = self._make_redis_stopped_user(runner_id, trigger="user:all")

        with patch.object(pu, "_cleanup_process_state") as mock_cleanup:
            cl._reconnect_surviving_runners(redis)

        mock_cleanup.assert_not_called()

    def test_orphan_stopped_user_skips_cleanup(self):
        """R: orphan scan에서 발견된 stopped+user orphan 러너 → cleanup 스킵"""
        cl = _load_listener()
        pu = _get_process_utils()
        _reset_shared_state()
        orphan_id = "su-orphan-003"
        redis = self._make_redis_orphan_stopped_user(orphan_id, trigger="user")

        with patch.object(pu, "_cleanup_process_state") as mock_cleanup, \
             patch("threading.Thread"):
            cl._reconnect_surviving_runners(redis)

        # orphan scan에서도 cleanup 호출 없어야 함
        for call_args in mock_cleanup.call_args_list:
            assert orphan_id not in str(call_args), (
                f"orphan stopped+user runner '{orphan_id}'가 cleanup됨."
            )
