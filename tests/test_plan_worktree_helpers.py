"""
plan_worktree_helpers.py 단위 테스트

대상 함수:
- is_worktree_active()
- is_plan_archived()
- has_unmerged_commits()
"""
import sys
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# scripts/ 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from plan_worktree_helpers import (
    is_worktree_active,
    is_plan_archived,
    has_unmerged_commits,
    resolve_active_plan_file,
)


# ---------------------------------------------------------------------------
# is_worktree_active
# ---------------------------------------------------------------------------

def _write_plan(tmp_path: Path, branch: str | None, worktree: str | None) -> Path:
    """plan 파일 생성 헬퍼"""
    plan = tmp_path / "docs" / "plan" / "2026-01-01_test.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Test Plan\n", "> 상태: 구현중\n"]
    if branch:
        lines.append(f"> branch: {branch}\n")
    if worktree:
        lines.append(f"> worktree: {worktree}\n")
    plan.write_text("".join(lines), encoding="utf-8")
    return plan


def test_is_worktree_active_exists_R(tmp_path):
    """R: worktree 디렉토리와 .git 파일 존재 → (True, branch, path)"""
    wt_dir = tmp_path / ".worktrees" / "test"
    wt_dir.mkdir(parents=True)
    (wt_dir / ".git").write_text("gitdir: ../../.git/worktrees/test")

    plan = _write_plan(tmp_path, "plan/test", ".worktrees/test")
    active, branch, wt_abs = is_worktree_active(str(plan), tmp_path)

    assert active is True
    assert branch == "plan/test"
    assert wt_abs is not None
    assert Path(wt_abs).is_dir()


def test_is_worktree_active_header_only_no_dir_B(tmp_path):
    """B: plan 헤더에 필드 있지만 디렉토리 미생성 → (False, None, None)"""
    plan = _write_plan(tmp_path, "plan/test", ".worktrees/test")
    active, branch, wt_abs = is_worktree_active(str(plan), tmp_path)

    assert active is False
    assert branch is None
    assert wt_abs is None


def test_is_worktree_active_no_header_B(tmp_path):
    """B: plan 헤더에 branch/worktree 필드 없음 → (False, None, None)"""
    plan = _write_plan(tmp_path, None, None)
    active, branch, wt_abs = is_worktree_active(str(plan), tmp_path)

    assert active is False
    assert branch is None
    assert wt_abs is None


def test_is_worktree_active_dir_exists_no_git_B(tmp_path):
    """B: 디렉토리 존재하지만 .git 파일 없음 → (False, None, None)"""
    wt_dir = tmp_path / ".worktrees" / "test"
    wt_dir.mkdir(parents=True)
    # .git 파일 없음

    plan = _write_plan(tmp_path, "plan/test", ".worktrees/test")
    active, branch, wt_abs = is_worktree_active(str(plan), tmp_path)

    assert active is False
    assert branch is None
    assert wt_abs is None


# ---------------------------------------------------------------------------
# is_plan_archived
# ---------------------------------------------------------------------------

def test_is_plan_archived_true_R():
    """R: archive 경로 → True"""
    assert is_plan_archived("D:/work/docs/archive/2026-01-01_test.md") is True


def test_is_plan_archived_false_R():
    """R: plan 경로 → False"""
    assert is_plan_archived("D:/work/docs/plan/2026-01-01_test.md") is False


def test_is_plan_archived_false_plans_worktree_R():
    """R: plans worktree active plan 경로 → False"""
    assert is_plan_archived("D:/work/project/tools/monitor-page/.worktrees/plans/docs/plan/2026-01-01_test.md") is False


def test_is_plan_archived_backslash_B():
    """B: 백슬래시 경로 → True"""
    assert is_plan_archived("D:\\work\\docs\\archive\\test.md") is True


def test_is_plan_archived_empty_E():
    """E: 빈 문자열 → False"""
    assert is_plan_archived("") is False


def test_resolve_active_plan_file_prefers_plans_worktree_R(tmp_path):
    """R: legacy/docs와 plans/worktree가 같이 있으면 plans/worktree를 우선 선택"""
    legacy = tmp_path / "docs" / "plan" / "2026-01-01_test.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("# legacy\n", encoding="utf-8")

    plans = tmp_path / ".worktrees" / "plans" / "docs" / "plan" / "2026-01-01_test.md"
    plans.parent.mkdir(parents=True, exist_ok=True)
    plans.write_text("# plans\n", encoding="utf-8")

    resolved = resolve_active_plan_file(str(legacy), project_root=tmp_path)
    assert resolved == plans.resolve()


def test_resolve_active_plan_file_returns_existing_input_path_B(tmp_path):
    """B: plans/worktree가 없어도 입력 경로가 실제 파일이면 그대로 반환"""
    legacy = tmp_path / "docs" / "plan" / "2026-01-02_test.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("# legacy only\n", encoding="utf-8")

    resolved = resolve_active_plan_file(str(legacy), project_root=tmp_path)
    assert resolved == legacy.resolve()


def test_resolve_active_plan_file_keeps_current_physical_path_R(tmp_path):
    """R: 현재 active physical path(.worktrees/plans)를 입력하면 그대로 유지"""
    current = tmp_path / ".worktrees" / "plans" / "docs" / "plan" / "2026-01-03_test.md"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text("# plans physical\n", encoding="utf-8")

    resolved = resolve_active_plan_file(str(current), project_root=tmp_path)
    assert resolved == current.resolve()


# ---------------------------------------------------------------------------
# has_unmerged_commits
# ---------------------------------------------------------------------------

def test_has_unmerged_commits_true_R(tmp_path):
    """R: git log 출력 있음 → True (독자 커밋 있음)"""
    with patch("plan_worktree_helpers.subprocess") as mock_sp:
        mock_result = MagicMock()
        mock_result.stdout = "abc1234 feat: some commit\n"
        mock_result.returncode = 0
        mock_sp.run.return_value = mock_result

        result = has_unmerged_commits("impl/test-branch", tmp_path)
        assert result is True


def test_has_unmerged_commits_false_B(tmp_path):
    """B: git log 출력 빈 문자열 → False (독자 커밋 없음)"""
    with patch("plan_worktree_helpers.subprocess") as mock_sp:
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0
        mock_sp.run.return_value = mock_result

        result = has_unmerged_commits("impl/test-branch", tmp_path)
        assert result is False


def test_has_unmerged_commits_exception_E(tmp_path):
    """E: subprocess 예외 발생 → True (보수적 fallback)"""
    with patch("plan_worktree_helpers.subprocess") as mock_sp:
        mock_sp.run.side_effect = Exception("git not found")

        result = has_unmerged_commits("impl/test-branch", tmp_path)
        assert result is True
