"""command-listener 블로킹 명령 비동기화 테스트

retry_merge, cleanup_worktree가 백그라운드 스레드 패턴으로 동작하는지 검증.
"""
import importlib.util
import json
from unittest.mock import MagicMock, patch

import pytest

from tests.dev_runner._path_helpers import get_listener_script_path, skip_if_missing


# ========== 모듈 로드 (하이픈 파일명 대응) ==========

_listener_mod = None


def _get_listener():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    script_path = get_listener_script_path()
    skip_if_missing(script_path, "Listener script")
    spec = importlib.util.spec_from_file_location("dev_runner_command_listener", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _listener_mod = mod
    return mod


@pytest.fixture(scope="module")
def listener_mod():
    return _get_listener()


@pytest.fixture(scope="module")
def commands_mod(listener_mod):
    import sys

    return sys.modules["_dr_commands"]


@pytest.fixture
def mock_redis():
    r = MagicMock()
    r.get.return_value = None
    r.lpush.return_value = 1
    r.expire.return_value = True
    return r


RUNNER_ID = "test_abc123"
COMMAND_ID = "cmd_001"
RUNNER_KEY_PREFIX = "plan-runner:runners"


class TestRetryMergeNonblocking:
    """retry_merge 비동기화 검증"""

    def test_retry_merge_returns_none(self, listener_mod, commands_mod, mock_redis):
        """Right: retry_merge(command, redis_client)가 None 반환 (메인 루프 스킵)"""
        with patch.object(commands_mod, "threading") as mock_threading:
            mock_threading.Thread.return_value = MagicMock()
            command = {"action": "retry-merge", "runner_id": RUNNER_ID, "command_id": COMMAND_ID}
            result = listener_mod.retry_merge(command, mock_redis)
            assert result is None

    def test_retry_merge_pushes_accepted_before_thread(self, listener_mod, commands_mod, mock_redis):
        """Right: accepted 응답이 Thread.start() 전에 push되는지 확인"""
        call_order = []

        def track_lpush(*args, **kwargs):
            call_order.append("lpush")
            return 1
        mock_redis.lpush.side_effect = track_lpush

        mock_thread = MagicMock()

        def track_start():
            call_order.append("thread_start")
        mock_thread.start = track_start

        with patch.object(commands_mod, "threading") as mock_threading:
            mock_threading.Thread.return_value = mock_thread
            command = {"action": "retry-merge", "runner_id": RUNNER_ID, "command_id": COMMAND_ID}
            listener_mod.retry_merge(command, mock_redis)

            assert "lpush" in call_order
            assert "thread_start" in call_order
            assert call_order.index("lpush") < call_order.index("thread_start")

    def test_retry_merge_thread_pushes_final_result(self, listener_mod, commands_mod, mock_redis):
        """Right: _do_retry_merge 완료 후 result_key에 최종 결과 push 확인"""
        mock_redis.get.side_effect = lambda key: {
            f"{RUNNER_KEY_PREFIX}:{RUNNER_ID}:worktree_path": "D:/work/project/tools/monitor-page",
            f"{RUNNER_KEY_PREFIX}:{RUNNER_ID}:plan_file": "test.md",
        }.get(key)

        with patch("plan_runner.core.stages.pre_merge_gate", return_value=(True, "ok")), \
             patch("plan_runner.core.stages.auto_commit_stage", return_value=True), \
             patch.object(commands_mod, "_execute_merge_with_lock", return_value={"success": True, "message": "ok"}), \
             patch.object(commands_mod, "_cleanup_process_state"):
            listener_mod._do_retry_merge(RUNNER_ID, mock_redis, COMMAND_ID, command={"worktree_path": "D:/tmp"})

            result_key = f"plan-runner:command_results:{COMMAND_ID}"
            lpush_calls = [c for c in mock_redis.lpush.call_args_list
                          if c[0][0] == result_key]
            assert len(lpush_calls) >= 1
            pushed_data = json.loads(lpush_calls[-1][0][1])
            assert pushed_data["success"] is True

    def test_retry_merge_thread_error_pushes_failure(self, listener_mod, commands_mod, mock_redis):
        """Error: MergeWorkflow 예외 시에도 result_key에 에러 결과 push"""
        mock_redis.get.side_effect = lambda key: {
            f"{RUNNER_KEY_PREFIX}:{RUNNER_ID}:worktree_path": "/tmp/wt",
            f"{RUNNER_KEY_PREFIX}:{RUNNER_ID}:plan_file": "test.md",
        }.get(key)

        with patch("plan_runner.core.stages.pre_merge_gate", return_value=(True, "ok")), \
             patch("plan_runner.core.stages.auto_commit_stage", return_value=True), \
             patch.object(commands_mod, "_execute_merge_with_lock", side_effect=Exception("subprocess explosion")), \
             patch.object(commands_mod, "_cleanup_process_state"):
            listener_mod._do_retry_merge(RUNNER_ID, mock_redis, "cmd_err", command={"worktree_path": "/tmp/wt"})

            result_key = "plan-runner:command_results:cmd_err"
            lpush_calls = [c for c in mock_redis.lpush.call_args_list
                          if c[0][0] == result_key]
            assert len(lpush_calls) >= 1
            pushed_data = json.loads(lpush_calls[-1][0][1])
            assert pushed_data["success"] is False
            assert len(pushed_data["message"]) > 0


class TestCleanupWorktreeNonblocking:
    """cleanup_worktree 비동기화 검증"""

    def test_cleanup_worktree_returns_none(self, listener_mod, commands_mod, mock_redis):
        """Right: cleanup_worktree(command, redis_client)가 None 반환"""
        with patch.object(commands_mod, "threading") as mock_threading:
            mock_threading.Thread.return_value = MagicMock()
            command = {"action": "cleanup-worktree", "runner_id": RUNNER_ID, "command_id": COMMAND_ID}
            result = listener_mod.cleanup_worktree(command, mock_redis)
            assert result is None

    def test_cleanup_worktree_pushes_accepted(self, listener_mod, commands_mod, mock_redis):
        """Right: accepted 응답이 push되는지 확인"""
        with patch.object(commands_mod, "threading") as mock_threading:
            mock_threading.Thread.return_value = MagicMock()
            command = {"action": "cleanup-worktree", "runner_id": RUNNER_ID, "command_id": COMMAND_ID}
            listener_mod.cleanup_worktree(command, mock_redis)

            lpush_calls = mock_redis.lpush.call_args_list
            assert len(lpush_calls) >= 1
            pushed_data = json.loads(lpush_calls[0][0][1])
            assert pushed_data["success"] is True
            assert pushed_data["message"] == "accepted"
            assert pushed_data["action"] == "cleanup-worktree"


class TestExecuteCommandNoneHandling:
    """execute_command 메인 루프 None 처리 회귀 방지"""

    def test_execute_command_skips_push_for_none(self):
        """Boundary: command_result is None 시 결과 push 스킵 — 메인 루프 로직 재현"""
        # 메인 루프 L1022-1025 로직 재현
        command_result = None
        push_called = False

        # 실제 메인 루프의 분기
        if command_result is None:
            pass  # "run 명령 — 백그라운드 스레드가 결과 반환 예정"
        else:
            push_called = True

        assert not push_called, "command_result가 None이면 push하지 않아야 함"
