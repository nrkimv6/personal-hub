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


# ========== TC #19: B(Boundary) — 3회 재시도 후에도 dirty → merge 중단 ==========

class TestPreMergeGateInlineDirty3xFail:
    """test_pre_merge_gate_inline_dirty_3x_fail: dirty 상태 3회 재시도 후에도 실패 → merge 중단"""

    def test_pre_merge_gate_inline_dirty_3x_fail(self, cl, tmp_path):
        """B(Boundary): pre_merge_gate 4회 모두 (False, dirty) → merge_status='error', _cleanup_process_state 호출"""
        # Arrange
        worktree_dir = tmp_path / "worktree"
        worktree_dir.mkdir()

        redis, store = _make_redis(str(worktree_dir), branch="plan/test-branch")

        mock_MergeWorkflow = MagicMock()

        # pre_merge_gate: 4회 모두 dirty 반환 (1차 초기 + 3회 재시도)
        gate_side_effects = [
            (False, "git dirty 상태: M app/foo.py"),
            (False, "git dirty 상태: M app/foo.py"),
            (False, "git dirty 상태: M app/foo.py"),
            (False, "git dirty 상태: M app/foo.py"),
        ]

        # Act
        with patch.object(cl, "_cleanup_process_state") as mock_cleanup, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock", return_value=True), \
             patch("plan_runner.core.pipeline.pre_merge_gate", side_effect=gate_side_effects) as mock_gate, \
             patch("plan_runner.core.pipeline.auto_commit_stage", return_value=True) as mock_auto_commit, \
             patch("merge_workflow.MergeWorkflow", mock_MergeWorkflow), \
             patch("worktree_manager.WorktreeManager.remove", return_value=None), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

            cl._do_inline_merge("test-runner", redis)

        # Assert: auto_commit_stage 3회 호출 (재시도 3회)
        assert mock_auto_commit.call_count == 3, \
            f"auto_commit_stage 호출 횟수 기대 3, 실제 {mock_auto_commit.call_count}"

        # Assert: merge_status가 "error"로 설정됨
        merge_status = store.get(f"{RUNNER_KEY_PREFIX}:test-runner:merge_status")
        assert merge_status == "error", \
            f"merge_status 기대 'error', 실제 '{merge_status}'"

        # Assert: MergeWorkflow.run() 미호출 (merge 중단)
        mock_MergeWorkflow.assert_not_called()

        # Assert: _cleanup_process_state 호출됨 (early return 시 + finally 블록에서 각 1회, 총 2회 이상)
        mock_cleanup.assert_called()


# ========== TC #20: E(Error) — main 브랜치 아닐 때 merge 중단 ==========

class TestPreMergeGateInlineNotMain:
    """test_pre_merge_gate_inline_not_main: main 브랜치 아닐 때 즉시 에러 처리"""

    def test_pre_merge_gate_inline_not_main(self, cl, tmp_path):
        """E(Error): pre_merge_gate (False, 'main 브랜치가 아님') → merge_status='error', MergeWorkflow 미호출"""
        # Arrange
        worktree_dir = tmp_path / "worktree"
        worktree_dir.mkdir()

        redis, store = _make_redis(str(worktree_dir), branch="plan/test-branch")

        mock_MergeWorkflow = MagicMock()

        # Act
        with patch.object(cl, "_cleanup_process_state") as mock_cleanup, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock", return_value=True), \
             patch("plan_runner.core.pipeline.pre_merge_gate",
                   return_value=(False, "main 브랜치가 아님")) as mock_gate, \
             patch("plan_runner.core.pipeline.auto_commit_stage") as mock_auto_commit, \
             patch("merge_workflow.MergeWorkflow", mock_MergeWorkflow), \
             patch("worktree_manager.WorktreeManager.remove", return_value=None), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

            cl._do_inline_merge("test-runner", redis)

        # Assert: pre_merge_gate 1회만 호출 (재시도 없이 즉시 중단)
        mock_gate.assert_called_once()

        # Assert: auto_commit_stage 미호출 (dirty 아닌 경우 커밋 시도 안 함)
        mock_auto_commit.assert_not_called()

        # Assert: MergeWorkflow.run() 미호출 (merge 중단)
        mock_MergeWorkflow.assert_not_called()

        # Assert: merge_status가 "error"로 설정됨
        merge_status = store.get(f"{RUNNER_KEY_PREFIX}:test-runner:merge_status")
        assert merge_status == "error", \
            f"merge_status 기대 'error', 실제 '{merge_status}'"

        # Assert: _cleanup_process_state 호출됨
        mock_cleanup.assert_called()


# ========== TC #21: E(Error) — git checkout main 실패 시 MergeResult ==========

class TestMergeToMainCheckoutFail:
    """test_merge_to_main_checkout_fail: git checkout main returncode=1 → MergeResult(success=False) + stderr 포함"""

    def test_merge_to_main_checkout_fail(self, tmp_path):
        """E(Error): git checkout main 실패(returncode=1) → MergeResult(success=False, conflict=False, stderr 포함)"""
        from unittest.mock import patch, MagicMock
        import sys
        import importlib.util
        from pathlib import Path

        wm_path = Path(__file__).parent.parent.parent / "scripts" / "worktree_manager.py"
        if not wm_path.exists():
            pytest.skip(f"worktree_manager.py not found: {wm_path}")

        spec = importlib.util.spec_from_file_location("worktree_manager_tc21", wm_path)
        wm_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wm_mod)
        WorktreeManager = wm_mod.WorktreeManager
        MergeResult = wm_mod.MergeResult

        project_root = tmp_path / "repo"
        project_root.mkdir()
        base_dir = tmp_path / "worktrees"
        base_dir.mkdir()

        # git checkout main 실패 mock (returncode=1, stderr 포함)
        checkout_fail = MagicMock()
        checkout_fail.returncode = 1
        checkout_fail.stdout = ""
        checkout_fail.stderr = "error: Your local changes would be overwritten by checkout."

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return checkout_fail
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = WorktreeManager.merge_to_main(
                runner_id="test-runner",
                base_dir=base_dir,
                project_root=project_root,
                branch="plan/test-branch",
            )

        # Assert: success=False
        assert result.success is False, \
            f"checkout 실패 시 success=False 기대, 실제: {result.success}"

        # Assert: conflict=False (checkout 단계 실패이므로 merge 충돌 아님)
        assert result.conflict is False, \
            f"checkout 실패 시 conflict=False 기대, 실제: {result.conflict}"

        # Assert: message에 stderr 내용 포함
        assert "git checkout main 실패" in result.message, \
            f"message에 'git checkout main 실패' 포함 기대, 실제: '{result.message}'"
        assert "overwritten" in result.message, \
            f"message에 stderr 텍스트('overwritten') 포함 기대, 실제: '{result.message}'"


# ========== TC #22: R(Right) — merge 실패 시 stderr+stdout 모두 포함 ==========

class TestMergeToMainStderrStdoutBoth:
    """test_merge_to_main_stderr_stdout_both: merge 실패 시 stderr+stdout 둘 다 message에 포함"""

    def test_merge_to_main_stderr_stdout_both(self, tmp_path):
        """R(Right): merge 실패 mock — stderr='error A', stdout='output B' → message에 둘 다 포함"""
        from unittest.mock import patch, MagicMock
        import sys
        import importlib.util
        from pathlib import Path

        wm_path = Path(__file__).parent.parent.parent / "scripts" / "worktree_manager.py"
        if not wm_path.exists():
            pytest.skip(f"worktree_manager.py not found: {wm_path}")

        spec = importlib.util.spec_from_file_location("worktree_manager_tc22", wm_path)
        wm_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wm_mod)
        WorktreeManager = wm_mod.WorktreeManager
        MergeResult = wm_mod.MergeResult

        project_root = tmp_path / "repo"
        project_root.mkdir()
        base_dir = tmp_path / "worktrees"
        base_dir.mkdir()

        # git checkout main 성공, git merge 실패 (returncode=1, stderr+stdout 모두 있음)
        checkout_ok = MagicMock()
        checkout_ok.returncode = 0
        checkout_ok.stdout = ""
        checkout_ok.stderr = ""

        merge_fail = MagicMock()
        merge_fail.returncode = 1
        merge_fail.stdout = "output B"
        merge_fail.stderr = "error A"

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return checkout_ok
            if "merge-base" in cmd:
                # not an ancestor → proceed with actual merge
                not_ancestor = MagicMock()
                not_ancestor.returncode = 1
                return not_ancestor
            if "merge" in cmd:
                return merge_fail
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = WorktreeManager.merge_to_main(
                runner_id="test-runner",
                base_dir=base_dir,
                project_root=project_root,
                branch="plan/test-branch",
            )

        # Assert: success=False (merge 실패)
        assert result.success is False, \
            f"merge 실패 시 success=False 기대, 실제: {result.success}"

        # Assert: message에 stderr("error A")와 stdout("output B") 모두 포함
        assert "error A" in result.message, \
            f"message에 stderr 텍스트('error A') 포함 기대, 실제: '{result.message}'"
        assert "output B" in result.message, \
            f"message에 stdout 텍스트('output B') 포함 기대, 실제: '{result.message}'"


# ========== TC #23: B(Boundary) — worktree 커밋 0개 → skip ==========

class TestWorkflowRunNoCommitsSkip:
    """test_workflow_run_no_commits_skip: worktree 커밋 0개 + diff 없음 → WorkflowResult(merged=True, message="변경사항 없음 — skip")"""

    def test_workflow_run_no_commits_skip(self, tmp_path):
        """B(Boundary): git log main..{branch} 빈 출력 + git diff 빈 출력 → merge skip 반환"""
        import sys
        import importlib.util
        from pathlib import Path
        from unittest.mock import patch, MagicMock

        scripts_dir = Path(__file__).parent.parent.parent / "scripts"
        wf_path = scripts_dir / "merge_workflow.py"
        if not wf_path.exists():
            pytest.skip(f"merge_workflow.py not found: {wf_path}")

        # scripts 디렉토리를 sys.path에 추가하여 worktree_manager 등 import 가능하게 함
        scripts_dir_str = str(scripts_dir)
        if scripts_dir_str not in sys.path:
            sys.path.insert(0, scripts_dir_str)

        spec = importlib.util.spec_from_file_location("merge_workflow_tc23", wf_path)
        wf_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wf_mod)
        MergeWorkflow = wf_mod.MergeWorkflow
        WorkflowResult = wf_mod.WorkflowResult

        project_root = tmp_path / "repo"
        project_root.mkdir()
        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()
        base_dir = tmp_path / "worktrees"
        base_dir.mkdir()

        redis = MagicMock()
        redis.publish.return_value = 0
        redis.lrange.return_value = []
        redis.set.return_value = True

        def fake_subprocess_run(cmd, **kwargs):
            cmd_list = list(cmd)
            # git add, git commit → 성공 (nothing to commit)
            if cmd_list[:2] == ["git", "add"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd_list[:2] == ["git", "commit"]:
                return MagicMock(returncode=1, stdout="nothing to commit", stderr="")
            # git log main..branch --oneline → 빈 출력 (커밋 0개)
            if cmd_list[:2] == ["git", "log"] and "--oneline" in cmd_list:
                return MagicMock(returncode=0, stdout="", stderr="")
            # git diff main..branch → 빈 출력 (변경사항 없음)
            if cmd_list[:2] == ["git", "diff"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        wf = MergeWorkflow(project_root=project_root, redis_client=redis)

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = wf.run(
                runner_id="test-runner",
                worktree_path=worktree_path,
                base_dir=base_dir,
                branch="plan/test-branch",
            )

        # Assert: merged=True (skip이지만 성공으로 처리)
        assert result.merged is True, \
            f"merged=True 기대 (skip), 실제: {result.merged}"

        # Assert: message에 "변경사항 없음" 포함
        assert "변경사항 없음" in result.message, \
            f"message에 '변경사항 없음' 포함 기대, 실제: '{result.message}'"

        # Assert: skip 키워드 포함
        assert "skip" in result.message, \
            f"message에 'skip' 포함 기대, 실제: '{result.message}'"

        # Assert: conflict=False
        assert result.conflict is False, \
            f"conflict=False 기대 (skip), 실제: {result.conflict}"
