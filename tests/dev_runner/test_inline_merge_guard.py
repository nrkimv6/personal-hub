"""
TC: _do_inline_merge() — pre_merge_gate + MergeWorkflow 호출 검증

대상 소스: scripts/dev-runner-command-listener.py
구현 항목: Phase 1 (pre_merge_gate 추가), Phase T1 TC #17
"""
import sys
import types
import importlib
import importlib.util
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ========== 모듈 로드 ==========

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "dev-runner-command-listener.py"

_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False

RUNNER_KEY_PREFIX = "plan-runner:runners"


def _load_listener():
    sys.modules.setdefault("listener_noise_filter", _mock_noise)
    spec = importlib.util.spec_from_file_location("_listener_inline_guard", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cl():
    if not _SCRIPT_PATH.exists():
        pytest.skip(f"Listener script not found: {_SCRIPT_PATH}")
    return _load_listener()


def _make_redis(worktree_path: str, branch: str = "plan/test-branch", plan_file: str = None):
    """필수 Redis 키들을 pre-set한 MagicMock 반환"""
    redis = MagicMock()

    store = {
        f"{RUNNER_KEY_PREFIX}:test-runner:merge_status": None,
        f"{RUNNER_KEY_PREFIX}:test-runner:merge_requested": "1",
        f"{RUNNER_KEY_PREFIX}:test-runner:worktree_path": worktree_path,
        f"{RUNNER_KEY_PREFIX}:test-runner:plan_file": plan_file or "docs/plan/test.md",
        f"{RUNNER_KEY_PREFIX}:test-runner:branch": branch,
        f"{RUNNER_KEY_PREFIX}:test-runner:stream_log_path": None,
        f"{RUNNER_KEY_PREFIX}:test-runner:log_file_path": None,
        f"{RUNNER_KEY_PREFIX}:test-runner:merge_status": None,
    }

    def _get(key):
        return store.get(key)

    def _set(key, value, **kwargs):
        store[key] = value
        return True

    redis.get.side_effect = _get
    redis.set.side_effect = _set
    redis.delete.return_value = 1
    redis.publish.return_value = 0
    redis.rpush.return_value = 1
    redis.lpush.return_value = 1
    redis.expire.return_value = True
    return redis, store


# ========== TC #17: R(Right) — clean 상태에서 pre_merge_gate 통과 후 merge 진행 ==========

class TestPreMergeGateInlineRightClean:
    """test_pre_merge_gate_inline_right_clean: clean 상태에서 gate 통과 → MergeWorkflow.run() 호출"""

    def test_pre_merge_gate_inline_right_clean(self, cl, tmp_path):
        """R(Right): pre_merge_gate (True, 'OK') 반환 → MergeWorkflow.run() 호출 확인"""
        # Arrange
        worktree_dir = tmp_path / "worktree"
        worktree_dir.mkdir()

        redis, store = _make_redis(str(worktree_dir), branch="plan/test-branch")

        mock_wf_result = MagicMock()
        mock_wf_result.merged = True
        mock_wf_result.tests_passed = True
        mock_wf_result.conflict = False
        mock_wf_result.message = "merge 성공"

        mock_workflow_instance = MagicMock()
        mock_workflow_instance.run.return_value = mock_wf_result

        mock_MergeWorkflow = MagicMock(return_value=mock_workflow_instance)

        # Act
        with patch.object(cl, "_cleanup_process_state"), \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock", return_value=True), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "OK")) as mock_gate, \
             patch("merge_workflow.MergeWorkflow", mock_MergeWorkflow), \
             patch("worktree_manager.WorktreeManager.remove", return_value=None), \
             patch("subprocess.run") as mock_subproc:

            # rebase subprocess 성공 모의
            mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

            cl._do_inline_merge("test-runner", redis)

        # Assert: pre_merge_gate 호출됨
        mock_gate.assert_called_once()

        # Assert: MergeWorkflow 인스턴스 생성됨
        mock_MergeWorkflow.assert_called_once()

        # Assert: workflow.run() 호출됨 (runner_id 포함)
        mock_workflow_instance.run.assert_called_once()
        call_kwargs = mock_workflow_instance.run.call_args
        assert call_kwargs is not None, "MergeWorkflow.run()이 호출되지 않음"

        # runner_id가 positional 또는 keyword로 전달됨
        args, kwargs = call_kwargs
        all_args = list(args) + list(kwargs.values())
        assert "test-runner" in all_args or kwargs.get("runner_id") == "test-runner", \
            f"runner_id가 MergeWorkflow.run() 인자에 없음. args={args}, kwargs={kwargs}"


# ========== TC #18: R(Right) — dirty 시 auto_commit_stage 호출 후 merge 진행 ==========

class TestPreMergeGateInlineDirtyAutoCommit:
    """test_pre_merge_gate_inline_dirty_auto_commit: dirty 상태 1회 → auto_commit_stage 호출 → 2차 gate 통과 → merge 진행"""

    def test_pre_merge_gate_inline_dirty_auto_commit(self, cl, tmp_path):
        """R(Right): pre_merge_gate 1차 (False, dirty), 2차 (True, OK) → auto_commit_stage 1회 호출, merge 진행"""
        # Arrange
        worktree_dir = tmp_path / "worktree"
        worktree_dir.mkdir()

        redis, store = _make_redis(str(worktree_dir), branch="plan/test-branch")

        mock_wf_result = MagicMock()
        mock_wf_result.merged = True
        mock_wf_result.tests_passed = True
        mock_wf_result.conflict = False
        mock_wf_result.message = "merge 성공"

        mock_workflow_instance = MagicMock()
        mock_workflow_instance.run.return_value = mock_wf_result

        mock_MergeWorkflow = MagicMock(return_value=mock_workflow_instance)

        # pre_merge_gate: 1차 dirty 반환, 2차 OK 반환
        gate_side_effects = [
            (False, "git dirty 상태: M app/foo.py"),
            (True, "OK"),
        ]

        # Act
        with patch.object(cl, "_cleanup_process_state"), \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock", return_value=True), \
             patch("plan_runner.core.pipeline.pre_merge_gate", side_effect=gate_side_effects) as mock_gate, \
             patch("plan_runner.core.pipeline.auto_commit_stage", return_value=True) as mock_auto_commit, \
             patch("merge_workflow.MergeWorkflow", mock_MergeWorkflow), \
             patch("worktree_manager.WorktreeManager.remove", return_value=None), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

            cl._do_inline_merge("test-runner", redis)

        # Assert: pre_merge_gate 2회 호출 (1차 dirty, 2차 OK)
        assert mock_gate.call_count == 2, \
            f"pre_merge_gate 호출 횟수 기대 2, 실제 {mock_gate.call_count}"

        # Assert: auto_commit_stage 1회 호출됨
        mock_auto_commit.assert_called_once(), \
            "dirty 감지 후 auto_commit_stage가 호출되지 않음"

        # Assert: 2차 gate 통과 후 merge 진행 (MergeWorkflow.run() 호출됨)
        mock_MergeWorkflow.assert_called_once()
        mock_workflow_instance.run.assert_called_once()
