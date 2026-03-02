"""
MergeWorkflow._wf_update() + run() 단위 테스트

Phase 2 TC:
  - test_wf_update_no_manager: B — workflow_manager=None → update_status 미호출
  - test_wf_update_not_found: B — get_by_runner_id=None → update_status 미호출
  - test_wf_update_success: R — status 전달 → update_status(id, status) 호출
  - test_wf_update_with_extra_kwargs: R — kwargs(commit_hash) 전달 확인
  - test_wf_update_exception_silent: E — update_status 예외 → 로깅만, 미전파
  - test_run_success: R — 머지+테스트 성공 → merging→merged + commit_hash
  - test_run_sets_merging_first: R — run() 시작 시 merging 상태 먼저 설정
  - test_run_merge_conflict: E — 머지 충돌 → merging→failed
  - test_run_test_failure: E — 테스트 실패 → merging→failed
  - test_run_no_manager: B — workflow_manager=None → 머지 진행 + workflow 업데이트 없음
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from merge_workflow import MergeWorkflow, WorkflowResult, TestResult
import worktree_manager as wm
from worktree_manager import MergeResult


@pytest.fixture
def mock_wf_manager():
    mgr = Mock()
    mgr.get_by_runner_id.return_value = {"id": 42, "runner_id": "runner-abc123"}
    mgr.update_status = Mock()
    return mgr


@pytest.fixture
def mock_redis():
    r = Mock()
    r.publish = Mock()
    r.lrange.return_value = []
    r.set = Mock()
    return r


@pytest.fixture
def project_root(tmp_path):
    return tmp_path


def _make_wf(project_root, mock_redis, wf_manager=None):
    return MergeWorkflow(project_root, mock_redis, python_path="python", workflow_manager=wf_manager)


# ── _wf_update 테스트 ──────────────────────────────────────────────

def test_wf_update_no_manager(project_root, mock_redis):
    """B(Boundary): workflow_manager=None → update_status 미호출"""
    wf = _make_wf(project_root, mock_redis, wf_manager=None)
    # 예외 없이 종료되어야 함
    wf._wf_update("runner-abc123", "merging")


def test_wf_update_not_found(project_root, mock_redis, mock_wf_manager):
    """B(Boundary): get_by_runner_id=None → update_status 미호출"""
    mock_wf_manager.get_by_runner_id.return_value = None
    wf = _make_wf(project_root, mock_redis, mock_wf_manager)
    wf._wf_update("runner-abc123", "merging")
    mock_wf_manager.update_status.assert_not_called()


def test_wf_update_success(project_root, mock_redis, mock_wf_manager):
    """R(Right): status 전달 → update_status(id, status) 호출"""
    wf = _make_wf(project_root, mock_redis, mock_wf_manager)
    wf._wf_update("runner-abc123", "merging")
    mock_wf_manager.update_status.assert_called_once_with(42, "merging")


def test_wf_update_with_extra_kwargs(project_root, mock_redis, mock_wf_manager):
    """R(Right): kwargs(commit_hash) → update_status에 그대로 전달"""
    wf = _make_wf(project_root, mock_redis, mock_wf_manager)
    wf._wf_update("runner-abc123", "merged", commit_hash="deadbeef")
    mock_wf_manager.update_status.assert_called_once_with(42, "merged", commit_hash="deadbeef")


def test_wf_update_exception_silent(project_root, mock_redis, mock_wf_manager):
    """E(Error): update_status 예외 → 로깅만, 예외 미전파"""
    mock_wf_manager.update_status.side_effect = Exception("DB locked")
    wf = _make_wf(project_root, mock_redis, mock_wf_manager)
    wf._wf_update("runner-abc123", "merging")  # 예외 없음


# ── run() 테스트 ──────────────────────────────────────────────────

def test_run_success(project_root, mock_redis, mock_wf_manager, tmp_path):
    """R(Right): 머지+테스트 성공 → merging→merged, commit_hash 저장"""
    wf = _make_wf(project_root, mock_redis, mock_wf_manager)
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    log_result = Mock()
    log_result.stdout = "abc123def456\n"

    with patch("subprocess.run", return_value=log_result), \
         patch.object(wm.WorktreeManager, "merge_to_main",
                      return_value=MergeResult(success=True, conflict=False, message="ok")), \
         patch.object(wm.WorktreeManager, "remove", return_value=None):

        wf.run_post_merge_tests = Mock(return_value=TestResult(passed=True, output="ok", exit_code=0))
        result = wf.run("runner-abc123", worktree_path, tmp_path)

    assert result.merged is True
    assert result.tests_passed is True

    calls = mock_wf_manager.update_status.call_args_list
    statuses = [c[0][1] for c in calls]
    assert statuses[0] == "merging"
    assert statuses[-1] == "merged"

    # commit_hash 저장 확인
    merged_call = next(c for c in calls if c[0][1] == "merged")
    assert "commit_hash" in merged_call[1]


def test_run_sets_merging_first(project_root, mock_redis, mock_wf_manager, tmp_path):
    """R(Right): run() 호출 시 첫 번째 update_status가 merging"""
    wf = _make_wf(project_root, mock_redis, mock_wf_manager)
    worktree_path = tmp_path / "worktree2"
    worktree_path.mkdir()

    with patch("subprocess.run", return_value=Mock(stdout="")), \
         patch.object(wm.WorktreeManager, "merge_to_main",
                      return_value=MergeResult(success=True, conflict=False, message="ok")), \
         patch.object(wm.WorktreeManager, "remove", return_value=None):

        wf.run_post_merge_tests = Mock(return_value=TestResult(passed=True, output="", exit_code=0))
        wf.run("runner-abc123", worktree_path, tmp_path)

    first_call = mock_wf_manager.update_status.call_args_list[0]
    assert first_call[0][1] == "merging"


def test_run_merge_conflict(project_root, mock_redis, mock_wf_manager, tmp_path):
    """E(Error): 머지 충돌 → merging→failed + error_message"""
    wf = _make_wf(project_root, mock_redis, mock_wf_manager)
    worktree_path = tmp_path / "worktree3"
    worktree_path.mkdir()

    with patch("subprocess.run"), \
         patch.object(wm.WorktreeManager, "merge_to_main",
                      return_value=MergeResult(success=False, conflict=True, message="충돌 발생")):

        result = wf.run("runner-abc123", worktree_path, tmp_path)

    assert result.merged is False

    calls = mock_wf_manager.update_status.call_args_list
    statuses = [c[0][1] for c in calls]
    assert "merging" in statuses
    assert "failed" in statuses

    failed_call = next(c for c in calls if c[0][1] == "failed")
    assert "error_message" in failed_call[1]


def test_run_test_failure(project_root, mock_redis, mock_wf_manager, tmp_path):
    """E(Error): 테스트 실패 → merging→failed"""
    wf = _make_wf(project_root, mock_redis, mock_wf_manager)
    worktree_path = tmp_path / "worktree4"
    worktree_path.mkdir()

    with patch("subprocess.run"), \
         patch.object(wm.WorktreeManager, "merge_to_main",
                      return_value=MergeResult(success=True, conflict=False, message="ok")), \
         patch.object(wm.WorktreeManager, "remove", return_value=None):

        wf.run_post_merge_tests = Mock(return_value=TestResult(passed=False, output="2 failed", exit_code=1))
        result = wf.run("runner-abc123", worktree_path, tmp_path)

    assert result.tests_passed is False

    statuses = [c[0][1] for c in mock_wf_manager.update_status.call_args_list]
    assert "failed" in statuses


def test_run_no_manager(project_root, mock_redis, tmp_path):
    """B(Boundary): workflow_manager=None → 머지 진행 + workflow update 없음"""
    wf = _make_wf(project_root, mock_redis, wf_manager=None)
    worktree_path = tmp_path / "worktree5"
    worktree_path.mkdir()

    with patch("subprocess.run", return_value=Mock(stdout="")), \
         patch.object(wm.WorktreeManager, "merge_to_main",
                      return_value=MergeResult(success=True, conflict=False, message="ok")), \
         patch.object(wm.WorktreeManager, "remove", return_value=None):

        wf.run_post_merge_tests = Mock(return_value=TestResult(passed=True, output="ok", exit_code=0))
        result = wf.run("runner-abc123", worktree_path, tmp_path)

    assert result.merged is True
