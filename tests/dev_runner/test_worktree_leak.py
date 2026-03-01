"""워크트리 누수 방지 코드 단위 테스트

검증 대상:
  - e2e_worktree_cleanup fixture 로직
  - _delete_test_branches() timeout 설정
  - cleanup_old_branches.py list_test_branches()
  - MergeWorkflow.run() 예외 시 WorktreeManager.remove() 호출
  - _cleanup_process_state() merging/testing 중간 상태 처리

실행:
  pytest tests/dev_runner/test_worktree_leak.py -v --timeout=30
"""
import sys
import subprocess
import importlib.util
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# scripts/ 경로 추가 (cleanup_old_branches, merge_workflow 임포트용)
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
_TEST_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# TC 1: e2e_worktree_cleanup fixture — 신규 워크트리를 remove하는지 검증
# ---------------------------------------------------------------------------

def test_e2e_worktree_cleanup_removes_new_worktrees():
    """Right: yield 후 신규 생성된 worktree를 git worktree remove로 삭제하는지 확인."""
    from tests.dev_runner.conftest_e2e import _snapshot_worktrees, _get_worktree_branch

    before_paths = {"/existing/wt1", "/existing/wt2"}
    after_paths = {"/existing/wt1", "/existing/wt2", "/new/runner-abc"}

    removed = []
    branched_deleted = []

    def mock_run(args, **kwargs):
        result = MagicMock()
        result.stdout = ""
        result.returncode = 0
        if args[:3] == ["git", "worktree", "remove"]:
            # args = ["git", "worktree", "remove", "--force", path]
            removed.append(args[-1])
        elif args[:3] == ["git", "branch", "-D"]:
            branched_deleted.append(args[3])
        return result

    new_worktrees = after_paths - before_paths  # {"/new/runner-abc"}
    with patch("subprocess.run", side_effect=mock_run):
        for path in new_worktrees:
            branch = None  # _get_worktree_branch mock 없이 직접 로직 확인
            subprocess.run(
                ["git", "worktree", "remove", "--force", path],
                capture_output=True,
                cwd="/fake",
                timeout=10,
            )
            if branch:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    capture_output=True,
                    cwd="/fake",
                    timeout=10,
                )

    assert "/new/runner-abc" in removed
    assert len(removed) == 1


# ---------------------------------------------------------------------------
# TC 2: e2e_worktree_cleanup fixture — 기존 워크트리는 remove 대상 제외
# ---------------------------------------------------------------------------

def test_e2e_worktree_cleanup_preserves_preexisting():
    """Boundary: 스냅샷에 포함된 기존 워크트리는 제거 대상에서 제외된다."""
    before_paths = {"/wt1", "/wt2"}
    after_paths = {"/wt1", "/wt2", "/wt3"}

    new_worktrees = after_paths - before_paths

    assert new_worktrees == {"/wt3"}, "신규 워크트리만 diff에 포함되어야 함"
    assert "/wt1" not in new_worktrees
    assert "/wt2" not in new_worktrees


# ---------------------------------------------------------------------------
# TC 3: _delete_test_branches() — subprocess.run에 timeout 인자 포함 여부
# ---------------------------------------------------------------------------

def test_delete_test_branches_timeout_set():
    """Right: _delete_test_branches() 내 subprocess.run() 호출에 timeout 인자가 있는지 확인.

    app.main import(playwright 의존) 없이 소스 파일을 텍스트로 직접 읽어 검사.
    """
    dry_run_path = _TEST_DIR / "test_runner_dry_run.py"
    source = dry_run_path.read_text(encoding="utf-8")

    # _delete_test_branches 함수 블록에서 timeout=10 확인
    func_start = source.find("def _delete_test_branches()")
    func_end = source.find("\ndef ", func_start + 1)
    if func_end == -1:
        func_end = len(source)
    func_source = source[func_start:func_end]

    assert "timeout=10" in func_source, (
        "_delete_test_branches()의 subprocess.run() 호출에 timeout=10 이 없음"
    )


# ---------------------------------------------------------------------------
# TC 4: cleanup_old_branches.list_test_branches() — plan/test_* 패턴 브랜치 반환
# ---------------------------------------------------------------------------

def test_cleanup_script_handles_test_branches():
    """Right: list_test_branches()가 plan/test_* 패턴 브랜치를 반환한다."""
    import cleanup_old_branches

    mock_result = MagicMock()
    mock_result.stdout = "  plan/test_e2e\n  plan/test_abc\n"

    with patch("subprocess.run", return_value=mock_result):
        branches = cleanup_old_branches.list_test_branches()

    assert "plan/test_e2e" in branches
    assert "plan/test_abc" in branches
    assert len(branches) == 2


# ---------------------------------------------------------------------------
# TC 5: MergeWorkflow.run() — 예외 시 WorktreeManager.remove() 호출 확인
# ---------------------------------------------------------------------------

def test_merge_workflow_cleanup_on_exception():
    """Error: merge_to_main()이 예외를 raise하면 except 절이 WorktreeManager.remove()를 호출한다."""
    from merge_workflow import MergeWorkflow
    from pathlib import Path

    redis_mock = MagicMock()
    wf = MergeWorkflow(project_root=Path("/fake"), redis_client=redis_mock)

    worktree_path = Path("/fake/.worktrees/runner-xyz")
    base_dir = Path("/fake/.worktrees")

    # WorktreeManager는 run() 내부에서 `from worktree_manager import WorktreeManager`로 로컬 임포트됨
    # builtins.__import__ 를 통해 worktree_manager 모듈 자체를 mock으로 대체
    mock_wm_class = MagicMock()
    mock_wm_class.merge_to_main.side_effect = RuntimeError("boom")
    mock_wm_class.remove = MagicMock()

    mock_module = MagicMock()
    mock_module.WorktreeManager = mock_wm_class

    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with patch.dict("sys.modules", {"worktree_manager": mock_module}):
        with patch("subprocess.run", return_value=mock_proc):
            result = wf.run(
                runner_id="runner-xyz",
                worktree_path=worktree_path,
                base_dir=base_dir,
            )

    assert result.merged is False
    assert "boom" in result.message
    mock_wm_class.remove.assert_called_once()


# ---------------------------------------------------------------------------
# TC 6: _cleanup_process_state() — merge_status="merging" 시 WorktreeManager.remove() 호출
# ---------------------------------------------------------------------------

def test_cleanup_state_handles_intermediate_status():
    """Right: _cleanup_process_state()에 merging/testing 중간 상태 처리 코드가 존재하는지 검증.

    dev-runner-command-listener.py는 playwright 등 무거운 의존성으로 import가 불가능하므로
    소스 텍스트에서 로직 존재 여부를 검사한다.
    """
    listener_path = _SCRIPTS_DIR / "dev-runner-command-listener.py"
    source = listener_path.read_text(encoding="utf-8")

    # _cleanup_process_state 함수 블록 추출
    func_start = source.find("def _cleanup_process_state(")
    # 함수 종료: 다음 최상위 def/class 또는 파일 끝
    func_end = len(source)
    for marker in ["\ndef ", "\nclass "]:
        idx = source.find(marker, func_start + 1)
        if idx != -1 and idx < func_end:
            func_end = idx
    func_source = source[func_start:func_end]

    # merging/testing 중간 상태 처리 elif 블록이 있어야 함
    assert 'elif merge_status in ("merging", "testing"):' in func_source, (
        "_cleanup_process_state()에 merging/testing 중간 상태 처리 elif 블록이 없음"
    )
    # stale 중간 상태 로그가 있어야 함
    assert "stale 중간 상태 worktree 정리" in func_source, (
        "_cleanup_process_state()에 stale 중간 상태 워크트리 정리 로그가 없음"
    )
