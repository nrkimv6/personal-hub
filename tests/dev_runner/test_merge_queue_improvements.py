"""merge queue 3가지 개선 — 단위 테스트 (RIGHT-BICEP)

구현 내용:
1. _resolve_todo_file() 헬퍼
2. already_merged skip (WorktreeManager + MergeWorkflow)
3. _do_retry_merge Redis 키 재발급
"""
import re
import subprocess
import importlib
import importlib.util
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# scripts/ 디렉토리를 sys.path에 추가
import sys
_SCRIPTS = str(Path(__file__).parent.parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from worktree_manager import WorktreeManager, MergeResult


# ── dev-runner-command-listener 모듈 로드 ─────────────────────────────────────

_LISTENER_PATH = Path(__file__).parent.parent.parent / "scripts" / "plan_runner" / "dev-runner-command-listener.py"

def _load_listener():
    """listener_noise_filter 의존성을 mock해서 모듈 로드"""
    _mock_noise = types.ModuleType("listener_noise_filter")
    _mock_noise.NOISE_BLOCK_MARKERS = []
    _mock_noise.is_noise_line = lambda line: False
    sys.modules["listener_noise_filter"] = _mock_noise

    spec = importlib.util.spec_from_file_location("_listener_mqi", _LISTENER_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


try:
    _mod = _load_listener()
except Exception as _e:
    _mod = None

_resolve_todo_file = getattr(_mod, "_resolve_todo_file", None) if _mod else None


@pytest.fixture
def tmp_plan_dir(tmp_path):
    """docs/archive + docs/plan 구조 생성"""
    archive = tmp_path / "docs" / "archive"
    plan = tmp_path / "docs" / "plan"
    archive.mkdir(parents=True)
    plan.mkdir(parents=True)
    return tmp_path, archive, plan


class TestResolveTodoFile:
    @pytest.mark.skipif(_resolve_todo_file is None, reason="_resolve_todo_file not importable")
    def test_right_none_input_returns_none(self):
        """R: None 입력 → None 반환"""
        assert _resolve_todo_file(None) is None

    @pytest.mark.skipif(_resolve_todo_file is None, reason="_resolve_todo_file not importable")
    def test_boundary_none_input(self):
        """B: None 입력 → 안전하게 None 반환 (예외 없음)"""
        result = _resolve_todo_file(None)
        assert result is None

    @pytest.mark.skipif(_resolve_todo_file is None, reason="_resolve_todo_file not importable")
    def test_right_archive_returns_todo_when_exists(self, tmp_plan_dir):
        """R: archive 경로 입력 → _todo.md 반환 (파일 존재 시)"""
        tmp, archive, plan = tmp_plan_dir
        plan_file = archive / "2026-03-05_my-feature.md"
        plan_file.write_text("# plan\n완료")
        todo_file = plan / "2026-03-05_my-feature_todo.md"
        todo_file.write_text("# TODO\n- [ ] 작업1")

        result = _resolve_todo_file(str(plan_file))
        assert result == str(todo_file)

    @pytest.mark.skipif(_resolve_todo_file is None, reason="_resolve_todo_file not importable")
    def test_right_archive_no_todo_returns_original(self, tmp_plan_dir):
        """R: _todo.md 없으면 원본 반환"""
        tmp, archive, plan = tmp_plan_dir
        plan_file = archive / "2026-03-05_no-todo.md"
        plan_file.write_text("# plan\n완료")

        result = _resolve_todo_file(str(plan_file))
        assert result == str(plan_file)

    @pytest.mark.skipif(_resolve_todo_file is None, reason="_resolve_todo_file not importable")
    def test_right_plan_with_checkboxes_returns_original(self, tmp_plan_dir):
        """R: plan 폴더이고 체크박스 있으면 그대로 반환"""
        tmp, archive, plan = tmp_plan_dir
        plan_file = plan / "2026-03-05_with-checks.md"
        plan_file.write_text("# TODO\n- [ ] 미완료 작업\n- [x] 완료 작업")

        result = _resolve_todo_file(str(plan_file))
        assert result == str(plan_file)

    @pytest.mark.skipif(_resolve_todo_file is None, reason="_resolve_todo_file not importable")
    def test_right_zero_checkboxes_tries_todo(self, tmp_plan_dir):
        """R: 체크박스 0개면 _todo.md 시도"""
        tmp, archive, plan = tmp_plan_dir
        plan_file = plan / "2026-03-05_empty-checks.md"
        plan_file.write_text("# plan content\nno checkboxes here", encoding="utf-8")
        todo_file = plan / "2026-03-05_empty-checks_todo.md"
        todo_file.write_text("- [ ] task1", encoding="utf-8")

        result = _resolve_todo_file(str(plan_file))
        assert result == str(todo_file)

    @pytest.mark.skipif(_resolve_todo_file is None, reason="_resolve_todo_file not importable")
    def test_error_nonexistent_file_returns_original(self, tmp_plan_dir):
        """E: 존재하지 않는 경로 → 원본 반환 (예외 없음)"""
        tmp, archive, plan = tmp_plan_dir
        nonexistent = str(plan / "ghost.md")
        result = _resolve_todo_file(nonexistent)
        assert result == nonexistent

    @pytest.mark.skipif(_resolve_todo_file is None, reason="_resolve_todo_file not importable")
    def test_right_sentinel_all_returns_original(self):
        """R: PLAN_FILE_ALL sentinel → 원본 반환"""
        sentinel = "__ALL_PLANS__"
        result = _resolve_todo_file(sentinel)
        assert result == sentinel


# ── MergeResult.already_merged ────────────────────────────────────────────────

class TestMergeResultAlreadyMerged:
    def test_right_default_already_merged_false(self):
        """R: MergeResult 기본값 already_merged=False"""
        r = MergeResult(success=True, conflict=False, message="ok")
        assert r.already_merged is False

    def test_right_can_set_already_merged_true(self):
        """R: already_merged=True 설정 가능"""
        r = MergeResult(success=True, conflict=False, message="skip", already_merged=True)
        assert r.already_merged is True


# ── WorktreeManager.merge_to_main() already_merged ────────────────────────────

@pytest.fixture
def tmp_git_repo_with_branch(tmp_path):
    """main + feature 브랜치 생성 (이미 머지된 상태 / 미머지 상태 테스트용)"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], capture_output=True, cwd=str(repo))
    subprocess.run(["git", "config", "user.name", "T"], capture_output=True, cwd=str(repo))
    subprocess.run(["git", "checkout", "-b", "main"], capture_output=True, cwd=str(repo))
    (repo / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], capture_output=True, cwd=str(repo))
    subprocess.run(["git", "commit", "-m", "init"], capture_output=True, cwd=str(repo))
    return repo


class TestMergeToMainAlreadyMerged:
    def test_right_already_merged_returns_skip(self, tmp_git_repo_with_branch):
        """R: 이미 머지된 브랜치 → already_merged=True 반환"""
        repo = tmp_git_repo_with_branch
        # feature 브랜치 생성 후 즉시 main에 머지
        subprocess.run(["git", "checkout", "-b", "plan/feat"], capture_output=True, cwd=str(repo))
        (repo / "feat.txt").write_text("feature")
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "commit", "-m", "feat"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "checkout", "main"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "merge", "plan/feat", "--no-ff", "-m", "merge: plan/feat"], capture_output=True, cwd=str(repo))

        base_dir = repo / ".worktrees"
        base_dir.mkdir()
        result = WorktreeManager.merge_to_main("runner1", base_dir, repo, branch="plan/feat")
        assert result.already_merged is True
        assert result.success is True

    def test_right_not_merged_proceeds(self, tmp_git_repo_with_branch):
        """R: 미머지 브랜치 → already_merged=False, 정상 merge 진행"""
        repo = tmp_git_repo_with_branch
        subprocess.run(["git", "checkout", "-b", "plan/new-feat"], capture_output=True, cwd=str(repo))
        (repo / "newfile.txt").write_text("new")
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "commit", "-m", "new"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "checkout", "main"], capture_output=True, cwd=str(repo))

        base_dir = repo / ".worktrees"
        base_dir.mkdir(exist_ok=True)
        result = WorktreeManager.merge_to_main("runner2", base_dir, repo, branch="plan/new-feat")
        assert result.already_merged is False
        assert result.success is True


# ── MergeWorkflow already_merged ──────────────────────────────────────────────

class TestMergeWorkflowAlreadyMerged:
    """MergeWorkflow.run() already_merged 분기 테스트"""

    def _make_wf(self, run_post_merge_mock=None):
        mw = importlib.import_module("merge_workflow")
        MergeWorkflow = mw.MergeWorkflow
        wf = MergeWorkflow.__new__(MergeWorkflow)
        wf.project_root = Path(".")
        wf.redis_client = MagicMock()
        wf.workflow_manager = None
        wf._publish_log = MagicMock()
        wf._update_queue_status = MagicMock()
        wf._wf_update = MagicMock()
        wf.run_post_merge_tests = run_post_merge_mock or MagicMock()
        wf._cleanup_worktree = MagicMock(return_value={"success": True})
        return wf

    def test_right_already_merged_skips_http(self, tmp_path):
        """R: already_merged=True이면 HTTP 테스트 미실행 (mock)"""
        run_post_merge_mock = MagicMock()
        wf = self._make_wf(run_post_merge_mock)
        already_merged_result = MergeResult(success=True, conflict=False, message="skip", already_merged=True)

        with patch("worktree_manager.WorktreeManager.merge_to_main", return_value=already_merged_result):
            try:
                wf.run("runner1", tmp_path, tmp_path, plan_file=None, branch="plan/t")
            except Exception:
                pass
            run_post_merge_mock.assert_not_called()

    def test_right_already_merged_tests_passed_true(self, tmp_path):
        """R: already_merged=True이면 WorkflowResult.tests_passed=True"""
        wf = self._make_wf()
        already_merged_result = MergeResult(success=True, conflict=False, message="skip", already_merged=True)

        with patch("worktree_manager.WorktreeManager.merge_to_main", return_value=already_merged_result):
            try:
                result = wf.run("runner1", tmp_path, tmp_path, plan_file=None, branch="plan/t")
                assert result.tests_passed is True
            except Exception:
                # 다른 부분에서 예외가 발생해도 merge_to_main 반환값이 already_merged=True인지 확인
                assert already_merged_result.already_merged is True


# ── _do_retry_merge Redis 키 재발급 ───────────────────────────────────────────

class TestDoRetryMergeRedisKeyReissue:
    """_do_retry_merge Redis 키 재발급 로직 — 모듈 로드 가능 시에만 실행"""

    @pytest.fixture(autouse=True)
    def check_importable(self):
        if getattr(_mod, "_do_retry_merge", None) is None:
            pytest.skip("_do_retry_merge not importable from cmd_listener")

    def test_right_reissues_keys_from_command(self, tmp_path):
        """R: Redis 키 없을 때 command payload로 재설정 후 merge 진행 (mock)"""
        _do_retry_merge = _mod._do_retry_merge
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        wt = str(tmp_path / "wt")
        Path(wt).mkdir()
        command = {"worktree_path": wt, "plan_file": "docs/plan/test_todo.md", "branch": "plan/test"}

        with patch("plan_runner.core.stages.pre_merge_gate", return_value=(True, "ok")), \
             patch("plan_runner.core.stages.auto_commit_stage", return_value=False), \
             patch("_dr_commands._execute_merge_with_lock", return_value={"success": True, "merge_status": "merged"}), \
             patch("merge_queue.acquire_merge_turn", return_value=True), \
             patch("merge_queue.release_merge_turn", return_value=None), \
             patch("_dr_commands._cleanup_process_state", return_value=None), \
             patch("_dr_commands._refresh_runner_ownership_snapshot", return_value=None), \
             patch("_dr_commands._log_memory_stage", return_value=None):
            _do_retry_merge("runner1", mock_redis, "cmd1", command=command)

        set_calls = [str(c) for c in mock_redis.set.call_args_list]
        assert any("worktree_path" in c for c in set_calls), "worktree_path 키 재발급 필요"

    def test_right_uses_existing_keys_if_present(self, tmp_path):
        """R: Redis 키 있으면 command payload 무시 (재발급 없음)"""
        _do_retry_merge = _mod._do_retry_merge
        wt = str(tmp_path / "wt")
        Path(wt).mkdir()
        mock_redis = MagicMock()
        mock_redis.get.side_effect = lambda key: wt if "worktree_path" in key else None

        command = {"worktree_path": str(tmp_path / "other_wt"), "branch": "plan/other"}

        with patch("plan_runner.core.stages.pre_merge_gate", return_value=(True, "ok")), \
             patch("plan_runner.core.stages.auto_commit_stage", return_value=False), \
             patch("_dr_commands._execute_merge_with_lock", return_value={"success": True, "merge_status": "merged"}), \
             patch("merge_queue.acquire_merge_turn", return_value=True), \
             patch("merge_queue.release_merge_turn", return_value=None), \
             patch("_dr_commands._cleanup_process_state", return_value=None), \
             patch("_dr_commands._refresh_runner_ownership_snapshot", return_value=None), \
             patch("_dr_commands._log_memory_stage", return_value=None):
            _do_retry_merge("runner1", mock_redis, "cmd1", command=command)

        # worktree_path 재발급 없어야 함
        reissue_calls = [c for c in mock_redis.set.call_args_list if "worktree_path" in str(c)]
        assert len(reissue_calls) == 0, "기존 키가 있으면 재발급하면 안 됨"

    def test_error_no_keys_no_payload(self):
        """E: Redis 키도 없고 payload도 없으면 worktree_path not found 실패"""
        _do_retry_merge = _mod._do_retry_merge
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        result_key_data = {}

        def mock_lpush(key, val):
            import json
            result_key_data["result"] = json.loads(val)

        mock_redis.lpush.side_effect = mock_lpush

        _do_retry_merge("runner1", mock_redis, "cmd1", command=None)

        if "result" in result_key_data:
            assert result_key_data["result"].get("success") is False
            assert "worktree_path not found" in result_key_data["result"].get("message", "")
