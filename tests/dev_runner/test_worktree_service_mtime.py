"""워크트리 서비스 mtime + plan-only + main dirty TC (T1/T2)"""
import re
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import app.modules.dev_runner.services.worktree_service as svc
from app.modules.dev_runner.schemas import (
    MainDirtyStatus,
    PlanOnlyBranch,
    WorktreeListResponse,
)


class TestFindPlanFileMtime:
    def test_find_plan_file_returns_mtime_RIGHT(self, tmp_path):
        """plan 파일 매칭 시 (path, mtime) 모두 non-None, mtime이 ISO 8601"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "2026-04-13_test-plan.md"
        plan_file.write_text(
            "# test\n\n> branch: impl/my-feat\n",
            encoding="utf-8",
        )

        result, mtime = svc.find_plan_file("impl/my-feat", repo_root=tmp_path)

        assert result is not None
        assert "test-plan" in result
        assert mtime is not None
        assert re.match(r"^\d{4}-\d{2}-\d{2}T", mtime), f"ISO 8601 아님: {mtime}"

    def test_find_plan_file_no_match_returns_none_tuple_ERROR(self, tmp_path):
        """매칭 없을 때 (None, None) 반환"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "other.md").write_text("> branch: impl/other\n", encoding="utf-8")

        result, mtime = svc.find_plan_file("impl/nonexistent", repo_root=tmp_path)

        assert result is None
        assert mtime is None

    def test_find_plan_file_prefers_plans_worktree_over_legacy_RIGHT(self, tmp_path):
        """같은 branch가 두 경로에 있으면 .worktrees/plans 경로를 우선 사용"""
        legacy_dir = tmp_path / "docs" / "plan"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "legacy.md").write_text("> branch: impl/same\n", encoding="utf-8")

        plans_dir = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        plans_dir.mkdir(parents=True)
        (plans_dir / "plans.md").write_text("> branch: impl/same\n", encoding="utf-8")

        result, mtime = svc.find_plan_file("impl/same", repo_root=tmp_path)

        assert result is not None
        assert result.replace("\\", "/").startswith(".worktrees/plans/docs/plan/")
        assert mtime is not None


class TestListPlanOnlyBranches:
    def test_list_plan_only_branches_filters_existing_RIGHT(self, tmp_path):
        """existing_branches에 없는 브랜치만 plan_only로 반환"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan-a.md").write_text("> branch: impl/a\n", encoding="utf-8")
        (plan_dir / "plan-b.md").write_text("> branch: impl/b\n", encoding="utf-8")

        plan_only, branch_unresolved = svc.list_plan_only_branches(
            existing_branches={"impl/a"}, repo_root=tmp_path
        )

        branches = [p.branch for p in plan_only]
        assert "impl/b" in branches
        assert "impl/a" not in branches

    def test_list_plan_only_branches_all_existing_BOUNDARY(self, tmp_path):
        """모든 브랜치가 existing_branches에 있으면 plan_only 빈 목록"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan-a.md").write_text("> branch: impl/a\n", encoding="utf-8")

        plan_only, _ = svc.list_plan_only_branches(
            existing_branches={"impl/a"}, repo_root=tmp_path
        )

        assert plan_only == []

    def test_list_plan_only_branches_no_branch_header_BOUNDARY(self, tmp_path):
        """> branch: 헤더 없는 plan 파일 → branch_unresolved에 포함"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "no-header.md").write_text(
            "# 헤더 없는 계획\n\n내용\n", encoding="utf-8"
        )

        _, branch_unresolved = svc.list_plan_only_branches(
            existing_branches=set(), repo_root=tmp_path
        )

        assert any("no-header" in b.plan_file for b in branch_unresolved)
        assert any(b.reason == "missing > branch header" for b in branch_unresolved)

    def test_list_plan_only_branches_scans_plans_worktree_RIGHT(self, tmp_path):
        """legacy docs/plan이 없어도 .worktrees/plans/docs/plan 스캔 결과를 반환"""
        plans_dir = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        plans_dir.mkdir(parents=True)
        (plans_dir / "plans-only.md").write_text("> branch: impl/plans-only\n", encoding="utf-8")

        plan_only, branch_unresolved = svc.list_plan_only_branches(
            existing_branches=set(), repo_root=tmp_path
        )

        assert any(p.branch == "impl/plans-only" for p in plan_only)
        assert branch_unresolved == []


class TestGetMainDirty:
    @pytest.mark.asyncio
    async def test_get_main_dirty_git_error_returns_empty_ERROR(self, tmp_path):
        """_run_git mock이 빈 문자열 반환 시 MainDirtyStatus(dirty_count=0) 반환"""
        with patch.object(svc, "_run_git", new=AsyncMock(return_value="")):
            result = await svc.get_main_dirty(repo_root=tmp_path)

        assert isinstance(result, MainDirtyStatus)
        assert result.dirty_count == 0
        assert result.files == []

    @pytest.mark.asyncio
    async def test_get_main_dirty_parses_porcelain_z_RIGHT(self, tmp_path):
        """NUL 구분 porcelain 출력 파싱 → dirty_count와 files 정확히"""
        mock_output = " M app/foo.py\x00?? new.txt\x00"
        with patch.object(svc, "_run_git", new=AsyncMock(return_value=mock_output)):
            result = await svc.get_main_dirty(repo_root=tmp_path)

        assert result.dirty_count == 2
        assert "app/foo.py" in result.files
        assert "new.txt" in result.files

    @pytest.mark.asyncio
    async def test_get_main_dirty_parses_rename_porcelain_z_RIGHT(self, tmp_path):
        """rename(R) 상태 → 다음 토큰(대상 경로)을 최종 파일로 집계"""
        mock_output = "R  old_name.py\x00new_name.py\x00"
        with patch.object(svc, "_run_git", new=AsyncMock(return_value=mock_output)):
            result = await svc.get_main_dirty(repo_root=tmp_path)

        assert "new_name.py" in result.files
        assert "old_name.py" not in result.files


class TestGetAllWorktrees:
    @pytest.mark.asyncio
    async def test_get_all_worktrees_empty_raw_returns_plan_only_RIGHT(self, tmp_path):
        """list_worktrees가 [] 반환해도 plan_only가 채워진 WorktreeListResponse 반환"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan-x.md").write_text("> branch: impl/x\n", encoding="utf-8")

        with (
            patch.object(svc, "list_worktrees", new=AsyncMock(return_value=[])),
            patch.object(svc, "get_main_dirty", new=AsyncMock(return_value=MainDirtyStatus())),
        ):
            result = await svc.get_all_worktrees(repo_root=tmp_path)

        assert isinstance(result, WorktreeListResponse)
        assert result.worktrees == []
        assert len(result.plan_only) >= 1
        assert any(p.branch == "impl/x" for p in result.plan_only)
