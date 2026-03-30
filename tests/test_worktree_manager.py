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


# ---------------------------------------------------------------------------
# T1-5: 브랜치 존재 시 -b 없이 worktree 생성 (재사용)
# ---------------------------------------------------------------------------

def test_create_reuses_existing_branch_right():
    """R(Right): 브랜치 존재 시 git worktree add에 -b 미포함, branch 인자 포함"""
    base_dir = Path("/fake/base")
    with patch("worktree_manager.subprocess.run") as mock_run, \
         patch.object(Path, "mkdir"), \
         patch.object(Path, "is_dir", return_value=False), \
         patch.object(WorktreeManager, "_apply_sparse_checkout"), \
         patch.object(WorktreeManager, "validate", return_value=True), \
         patch("worktree_manager.ensure_main_branch"):

        def run_side_effect(cmd, **kwargs):
            if cmd[:3] == ["git", "branch", "--list"]:
                return _make_run_result(0, stdout="  plan/2026-03-07_test-plan\n")
            return _make_run_result(0)

        mock_run.side_effect = run_side_effect
        worktree_path, branch = WorktreeManager.create("r1", base_dir, plan_file="2026-03-07_test-plan.md")

    worktree_add_calls = [
        c for c in mock_run.call_args_list
        if "worktree" in c[0][0] and "add" in c[0][0]
    ]
    assert len(worktree_add_calls) == 1
    cmd = worktree_add_calls[0][0][0]
    assert "-b" not in cmd
    assert branch in cmd


# ---------------------------------------------------------------------------
# T1-6: 브랜치 미존재 시 -b로 신규 생성
# ---------------------------------------------------------------------------

def test_create_new_branch_when_not_exists_right():
    """R(Right): 브랜치 미존재 시 git worktree add에 -b 포함"""
    base_dir = Path("/fake/base")
    with patch("worktree_manager.subprocess.run") as mock_run, \
         patch.object(Path, "mkdir"), \
         patch.object(Path, "is_dir", return_value=False), \
         patch.object(WorktreeManager, "_apply_sparse_checkout"), \
         patch.object(WorktreeManager, "validate", return_value=True), \
         patch("worktree_manager.ensure_main_branch"):

        def run_side_effect(cmd, **kwargs):
            if cmd[:3] == ["git", "branch", "--list"]:
                return _make_run_result(0, stdout="")
            return _make_run_result(0)

        mock_run.side_effect = run_side_effect
        worktree_path, branch = WorktreeManager.create("r1", base_dir, plan_file="2026-03-07_test-plan.md")

    worktree_add_calls = [
        c for c in mock_run.call_args_list
        if "worktree" in c[0][0] and "add" in c[0][0]
    ]
    assert len(worktree_add_calls) == 1
    cmd = worktree_add_calls[0][0][0]
    assert "-b" in cmd
    assert branch in cmd


# ---------------------------------------------------------------------------
# T1-7: 브랜치 존재 + 다른 worktree에서 checkout 중 → 복구 경로
# ---------------------------------------------------------------------------

def test_create_branch_exists_worktree_add_fails_boundary():
    """B(Boundary): 브랜치 존재 + worktree add (no -b) 실패 → 'already checked out' → 미머지 커밋 있음 → 기존 브랜치 재사용 성공"""
    base_dir = Path("/fake/base")
    from worktree_manager import WorktreeError
    no_b_call_count = {"n": 0}
    with patch("worktree_manager.subprocess.run") as mock_run, \
         patch.object(Path, "mkdir"), \
         patch.object(Path, "is_dir", return_value=False), \
         patch.object(WorktreeManager, "_apply_sparse_checkout"), \
         patch.object(WorktreeManager, "validate", return_value=True), \
         patch("worktree_manager.ensure_main_branch"):

        def run_side_effect(cmd, **kwargs):
            if cmd[:3] == ["git", "branch", "--list"]:
                return _make_run_result(0, stdout="  plan/2026-03-07_test-plan\n")
            if "worktree" in cmd and "add" in cmd and "-b" not in cmd:
                no_b_call_count["n"] += 1
                if no_b_call_count["n"] == 1:
                    return _make_run_result(1, stderr="already checked out")
                # 두 번째 (미머지 커밋 있음 경로 재시도) → 성공
                return _make_run_result(0)
            if cmd[:2] == ["git", "log"]:
                return _make_run_result(0, stdout="abc123 some commit\n")
            return _make_run_result(0)

        mock_run.side_effect = run_side_effect
        worktree_path, branch = WorktreeManager.create("r1", base_dir, plan_file="2026-03-07_test-plan.md")

    assert branch == "plan/2026-03-07_test-plan"


# ---------------------------------------------------------------------------
# T1-8: branch -D 실패 시 warning 로그 출력
# ---------------------------------------------------------------------------

def test_create_branch_delete_failure_logged_error(caplog):
    """E(Error): branch -D 실패 시 warning 로그 'branch -D 실패' 포함"""
    import logging
    base_dir = Path("/fake/base")
    with patch("worktree_manager.subprocess.run") as mock_run, \
         patch.object(Path, "mkdir"), \
         patch.object(Path, "is_dir", return_value=False), \
         patch.object(WorktreeManager, "_apply_sparse_checkout"), \
         patch.object(WorktreeManager, "validate", return_value=True), \
         patch("worktree_manager.ensure_main_branch"), \
         caplog.at_level(logging.WARNING, logger="worktree_manager"):

        call_count = {"n": 0}

        def run_side_effect(cmd, **kwargs):
            if cmd[:3] == ["git", "branch", "--list"]:
                return _make_run_result(0, stdout="")
            if "worktree" in cmd and "add" in cmd and "-b" in cmd:
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return _make_run_result(1, stderr="already exists")
                return _make_run_result(0)
            if cmd[:3] == ["git", "branch", "-D"]:
                return _make_run_result(1, stderr="error: branch is checked out")
            if cmd[:2] == ["git", "log"]:
                return _make_run_result(0, stdout="")
            return _make_run_result(0)

        mock_run.side_effect = run_side_effect
        WorktreeManager.create("r1", base_dir, plan_file="2026-03-07_test-plan.md")

    assert any("branch -D 실패" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# T1-9: 에러 메시지에 stdout + stderr 모두 포함
# ---------------------------------------------------------------------------

def test_create_error_message_includes_stdout_error():
    """E(Error): 최종 실패 시 WorktreeError 메시지에 stderr= 및 stdout= 포함"""
    base_dir = Path("/fake/base")
    from worktree_manager import WorktreeError
    with patch("worktree_manager.subprocess.run") as mock_run, \
         patch.object(Path, "mkdir"), \
         patch.object(Path, "is_dir", return_value=False), \
         patch("worktree_manager.ensure_main_branch"):

        def run_side_effect(cmd, **kwargs):
            if cmd[:3] == ["git", "branch", "--list"]:
                return _make_run_result(0, stdout="")
            if "worktree" in cmd and "add" in cmd:
                return _make_run_result(1, stderr="some error", stdout="some output")
            return _make_run_result(0)

        mock_run.side_effect = run_side_effect
        with pytest.raises(WorktreeError) as exc:
            WorktreeManager.create("r1", base_dir, plan_file="2026-03-07_test-plan.md")

    assert "stderr=" in str(exc.value)
    assert "stdout=" in str(exc.value)


# ---------------------------------------------------------------------------
# T3: 실제 git repo — dangling 브랜치 재사용 통합 TC
# ---------------------------------------------------------------------------

def test_create_with_dangling_branch_real_git(tmp_path):
    """T3(통합): 실제 git repo에서 dangling 브랜치 존재 시 재사용하여 worktree 생성 성공"""
    import subprocess as sp

    # 실제 git repo 초기화 (main 브랜치로)
    repo = tmp_path / "repo"
    repo.mkdir()
    sp.run(["git", "init", "-b", "main"], cwd=str(repo), capture_output=True)
    sp.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
    sp.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)
    (repo / "README.md").write_text("init")
    sp.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    sp.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True)

    # dangling 브랜치 생성 (worktree 없이 브랜치만)
    sp.run(["git", "branch", "plan/test-dangling"], cwd=str(repo), capture_output=True)

    # WorktreeManager.create() 호출 — 브랜치 존재 시 -b 없이 재사용해야 함
    # base_dir.parent가 git repo여야 함
    base_dir = repo / ".worktrees"
    worktree_path, branch = WorktreeManager.create("test", base_dir, plan_file="test-dangling.md")

    assert branch == "plan/test-dangling"
    assert (worktree_path / ".git").exists()
