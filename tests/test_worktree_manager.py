"""
WorktreeManager sparse-checkout 테스트.

RIGHT-BICEP:
- R(Right): 정상 동작 검증
- B(Boundary): 재사용 분기 검증
"""
import sys
from pathlib import Path
from unittest.mock import call, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from worktree_manager import WorktreeManager


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_run_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


# ---------------------------------------------------------------------------
# T1-1: _apply_sparse_checkout — sparse-checkout init + set 두 번 호출
# ---------------------------------------------------------------------------

def test_sparse_checkout_applied():
    """R(Right): _apply_sparse_checkout 호출 시 git sparse-checkout init/set 실행 확인"""
    worktree_path = Path("/fake/worktree")
    with patch("worktree_manager.subprocess.run") as mock_run:
        mock_run.return_value = _make_run_result()
        WorktreeManager._apply_sparse_checkout(worktree_path)

    calls = mock_run.call_args_list
    assert len(calls) == 2

    init_cmd = calls[0][0][0]
    assert init_cmd[:3] == ["git", "sparse-checkout", "init"]
    assert "--no-cone" in init_cmd

    set_cmd = calls[1][0][0]
    assert set_cmd[:3] == ["git", "sparse-checkout", "set"]
    assert "!/docs/plan/" in set_cmd
    assert "!/docs/archive/" in set_cmd
    assert "/*" in set_cmd


# ---------------------------------------------------------------------------
# T1-2: create() 정상 생성 후 sparse-checkout 적용 확인
# ---------------------------------------------------------------------------

def test_sparse_checkout_excludes_plan_dir():
    """R(Right): create() 성공 시 _apply_sparse_checkout 호출됨"""
    base_dir = Path("/fake/base")
    with patch("worktree_manager.subprocess.run") as mock_run, \
         patch.object(Path, "mkdir"), \
         patch.object(Path, "is_dir", return_value=False), \
         patch.object(WorktreeManager, "_apply_sparse_checkout") as mock_sparse:

        mock_run.return_value = _make_run_result(0)
        worktree_path, branch = WorktreeManager.create("r1", base_dir, plan_file="2026-03-07_test-plan.md")

    mock_sparse.assert_called_once_with(worktree_path)


# ---------------------------------------------------------------------------
# T1-3: tests/ 디렉토리는 제외 패턴에 포함되지 않음
# ---------------------------------------------------------------------------

def test_sparse_checkout_keeps_tests():
    """R(Right): sparse-checkout set 패턴에 tests 제외 패턴 없음"""
    worktree_path = Path("/fake/worktree")
    with patch("worktree_manager.subprocess.run") as mock_run:
        mock_run.return_value = _make_run_result()
        WorktreeManager._apply_sparse_checkout(worktree_path)

    set_cmd = mock_run.call_args_list[1][0][0]
    # tests/ 관련 제외 패턴이 없어야 함
    assert not any("tests" in p for p in set_cmd if p.startswith("!"))


# ---------------------------------------------------------------------------
# T1-4: 기존 worktree 재사용 분기(is_dir=True)에서도 sparse-checkout 적용
# ---------------------------------------------------------------------------

def test_sparse_checkout_reuse_branch():
    """B(Boundary): 기존 worktree 재사용 분기에서도 _apply_sparse_checkout 호출됨"""
    base_dir = Path("/fake/base")

    with patch("worktree_manager.subprocess.run") as mock_run, \
         patch.object(Path, "mkdir"), \
         patch.object(WorktreeManager, "_apply_sparse_checkout") as mock_sparse:

        # 첫 번째 git worktree add → "already exists" 에러
        # worktree_path.is_dir() 는 재사용 분기에서 True 반환
        def run_side_effect(cmd, **kwargs):
            if "worktree" in cmd and "add" in cmd:
                return _make_run_result(1, stderr="already exists")
            return _make_run_result(0)

        mock_run.side_effect = run_side_effect

        # is_dir patch: worktree_path 인스턴스에만 True 반환
        with patch.object(Path, "is_dir", return_value=True):
            worktree_path, branch = WorktreeManager.create("r1", base_dir, plan_file="2026-03-07_test-plan.md")

    mock_sparse.assert_called_once_with(worktree_path)
