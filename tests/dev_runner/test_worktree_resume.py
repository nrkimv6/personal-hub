"""dev-runner 워크트리 재사용 헬퍼 함수 유닛 테스트 — RIGHT-BICEP + CORRECT"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from plan_worktree_helpers import (
    is_plan_in_progress as _is_plan_in_progress,
    parse_plan_worktree_info as _parse_plan_worktree_info,
    write_plan_worktree_info as _write_plan_worktree_info,
)


# ── _is_plan_in_progress ─────────────────────────────────────────────────────

class TestIsPlanInProgress:
    def test_right_returns_true(self, tmp_path):
        """R: '> 상태: 구현중' 있는 plan → True"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n> 상태: 구현중\n\n## 내용", encoding="utf-8")
        assert _is_plan_in_progress(str(p)) is True

    def test_right_returns_false(self, tmp_path):
        """R: '> 상태: 완료' 있는 plan → False"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n> 상태: 완료\n\n## 내용", encoding="utf-8")
        assert _is_plan_in_progress(str(p)) is False

    def test_boundary_no_status(self, tmp_path):
        """B: '> 상태:' 줄 없는 plan → False"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n\n## 내용", encoding="utf-8")
        assert _is_plan_in_progress(str(p)) is False

    def test_boundary_empty_file(self, tmp_path):
        """B: 빈 파일 → False"""
        p = tmp_path / "plan.md"
        p.write_text("", encoding="utf-8")
        assert _is_plan_in_progress(str(p)) is False

    def test_error_nonexistent(self):
        """E: 존재하지 않는 파일 → False"""
        assert _is_plan_in_progress("/nonexistent/path/plan.md") is False


# ── _parse_plan_worktree_info ─────────────────────────────────────────────────

class TestParsePlanWorktreeInfo:
    def test_right_both_fields(self, tmp_path):
        """R: branch + worktree 둘 다 있음 → (branch, worktree) 반환"""
        p = tmp_path / "plan.md"
        p.write_text(
            "# 제목\n> 상태: 구현중\n> branch: impl/feature-abc\n> worktree: .worktrees/impl-feature-abc\n",
            encoding="utf-8"
        )
        branch, worktree = _parse_plan_worktree_info(str(p))
        assert branch == "impl/feature-abc"
        assert worktree == ".worktrees/impl-feature-abc"

    def test_right_no_fields(self, tmp_path):
        """R: 필드 없음 → (None, None) 반환"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n> 상태: 미시작\n", encoding="utf-8")
        branch, worktree = _parse_plan_worktree_info(str(p))
        assert branch is None
        assert worktree is None

    def test_boundary_only_branch(self, tmp_path):
        """B: branch만 있고 worktree 없음 → (branch, None)"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n> branch: impl/feature-abc\n", encoding="utf-8")
        branch, worktree = _parse_plan_worktree_info(str(p))
        assert branch == "impl/feature-abc"
        assert worktree is None

    def test_error_nonexistent(self):
        """E: 존재하지 않는 파일 → (None, None)"""
        branch, worktree = _parse_plan_worktree_info("/nonexistent/plan.md")
        assert branch is None
        assert worktree is None


# ── _write_plan_worktree_info ─────────────────────────────────────────────────

class TestWritePlanWorktreeInfo:
    def test_right_inserts_after_status(self, tmp_path):
        """R: 상태 줄 다음에 branch/worktree 삽입"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n> 상태: 구현중\n\n## 내용\n", encoding="utf-8")
        _write_plan_worktree_info(str(p), "impl/feat", ".worktrees/impl-feat")
        content = p.read_text(encoding="utf-8")
        assert "> branch: impl/feat" in content
        assert "> worktree: .worktrees/impl-feat" in content
        # 상태 줄 다음에 삽입됐는지 확인
        lines = content.splitlines()
        status_idx = next(i for i, l in enumerate(lines) if "상태:" in l)
        assert "> branch: impl/feat" in lines[status_idx + 1]

    def test_right_replaces_existing(self, tmp_path):
        """R: 이미 있으면 교체"""
        p = tmp_path / "plan.md"
        p.write_text(
            "# 제목\n> 상태: 구현중\n> branch: impl/old\n> worktree: .worktrees/impl-old\n",
            encoding="utf-8"
        )
        _write_plan_worktree_info(str(p), "impl/new", ".worktrees/impl-new")
        content = p.read_text(encoding="utf-8")
        assert "impl/new" in content
        assert "impl/old" not in content

    def test_boundary_no_status_line(self, tmp_path):
        """B: 상태 줄 없으면 제목(#) 다음에 삽입"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n\n## 내용\n", encoding="utf-8")
        _write_plan_worktree_info(str(p), "impl/feat", ".worktrees/impl-feat")
        content = p.read_text(encoding="utf-8")
        assert "> branch: impl/feat" in content
