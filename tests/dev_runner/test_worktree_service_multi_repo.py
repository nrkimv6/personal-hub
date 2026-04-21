"""멀티 레포 워크트리 서비스 TC (Phase 4 — T1/T2)"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import app.modules.dev_runner.services.worktree_service as svc
from app.modules.dev_runner.schemas import MainDirtyStatus, WorktreeListResponse


class TestRunGitRepoRoot:
    @pytest.mark.asyncio
    async def test_run_git_uses_given_repo_root_RIGHT(self, tmp_path):
        """_run_git에 repo_root 전달 시 해당 cwd로 subprocess 실행"""
        custom_path = tmp_path / "custom_repo"
        custom_path.mkdir()

        captured_kwargs = {}

        async def mock_exec(*args, **kwargs):
            captured_kwargs.update(kwargs)
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"output", b""))
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            await svc._run_git("status", repo_root=custom_path)

        assert captured_kwargs.get("cwd") == str(custom_path)

    @pytest.mark.asyncio
    async def test_run_git_default_repo_root_RIGHT(self):
        """repo_root 미지정 시 _REPO_ROOT 사용"""
        captured_kwargs = {}

        async def mock_exec(*args, **kwargs):
            captured_kwargs.update(kwargs)
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            await svc._run_git("status")

        assert captured_kwargs.get("cwd") == str(svc._REPO_ROOT)


class TestGetAllWorktreesRepoRoot:
    @pytest.mark.asyncio
    async def test_get_all_worktrees_nonexistent_path_BOUNDARY(self, tmp_path):
        """존재하지 않는 경로 전달 → 에러 전파 없이 빈 WorktreeListResponse 반환"""
        nonexistent = tmp_path / "does_not_exist"

        with patch.object(svc, "list_worktrees", new=AsyncMock(return_value=[])):
            result = await svc.get_all_worktrees(repo_root=nonexistent)

        assert isinstance(result, WorktreeListResponse)
        assert result.worktrees == []

    @pytest.mark.asyncio
    async def test_get_all_worktrees_default_repo_root_RIGHT(self, tmp_path):
        """기본값 호출 시 _REPO_ROOT 사용 확인"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)

        with (
            patch.object(svc, "list_worktrees", new=AsyncMock(return_value=[])),
            patch.object(svc, "get_main_dirty", new=AsyncMock(return_value=MainDirtyStatus())),
            patch.object(svc, "_REPO_ROOT", tmp_path),
        ):
            result = await svc.get_all_worktrees()

        assert isinstance(result, WorktreeListResponse)

    @pytest.mark.asyncio
    async def test_get_all_worktrees_skips_commit_log_when_ahead_zero_RIGHT(self, tmp_path):
        """ahead=0 브랜치는 git log를 호출하지 않고 commit_count=0 유지"""
        with (
            patch.object(
                svc,
                "list_worktrees",
                new=AsyncMock(
                    return_value=[
                        {
                            "branch": "impl/behind-only",
                            "worktree_path": str(tmp_path / ".worktrees" / "impl-behind-only"),
                            "locked": False,
                        }
                    ]
                ),
            ),
            patch.object(
                svc,
                "_scan_plan_file_index",
                return_value=({}, {}, []),
            ),
            patch.object(
                svc,
                "get_ahead_behind",
                new=AsyncMock(return_value=(0, 7)),
            ),
            patch.object(
                svc,
                "get_worktree_commits",
                new=AsyncMock(side_effect=AssertionError("ahead=0 브랜치에서 호출되면 안 됨")),
            ),
            patch.object(
                svc,
                "get_created_at",
                new=AsyncMock(side_effect=AssertionError("ahead=0 브랜치에서 호출되면 안 됨")),
            ),
            patch.object(
                svc,
                "get_main_dirty",
                new=AsyncMock(return_value=MainDirtyStatus()),
            ),
        ):
            result = await svc.get_all_worktrees(repo_root=tmp_path)

        assert len(result.worktrees) == 1
        assert result.worktrees[0].ahead == 0
        assert result.worktrees[0].behind == 7
        assert result.worktrees[0].commit_count == 0
        assert result.worktrees[0].created_at is None

    @pytest.mark.asyncio
    async def test_get_all_worktrees_prefers_batched_ahead_behind_RIGHT(self, tmp_path):
        """배치 ahead/behind 결과가 있으면 개별 rev-list 호출 없이 사용"""
        with (
            patch.object(
                svc,
                "list_worktrees",
                new=AsyncMock(
                    return_value=[
                        {
                            "branch": "impl/batched",
                            "worktree_path": str(tmp_path / ".worktrees" / "impl-batched"),
                            "locked": False,
                        }
                    ]
                ),
            ),
            patch.object(
                svc,
                "_scan_plan_file_index",
                return_value=({}, {}, []),
            ),
            patch.object(
                svc,
                "get_ahead_behind_map",
                new=AsyncMock(return_value={"impl/batched": (2, 5)}),
            ),
            patch.object(
                svc,
                "get_ahead_behind",
                new=AsyncMock(side_effect=AssertionError("배치 결과가 있으면 개별 rev-list 호출 금지")),
            ),
            patch.object(
                svc,
                "get_worktree_commits",
                new=AsyncMock(side_effect=AssertionError("v2 lite 응답에서 커밋 상세 호출 금지")),
            ),
            patch.object(
                svc,
                "get_created_at",
                new=AsyncMock(return_value="2026-04-21 10:00:00 +0900"),
            ),
            patch.object(
                svc,
                "get_main_dirty",
                new=AsyncMock(return_value=MainDirtyStatus()),
            ),
        ):
            result = await svc.get_all_worktrees(repo_root=tmp_path)

        assert len(result.worktrees) == 1
        assert result.worktrees[0].ahead == 2
        assert result.worktrees[0].behind == 5
        assert result.worktrees[0].commit_count == 2
        assert result.worktrees[0].created_at == "2026-04-21 10:00:00 +0900"


class TestGetAllWorktreesWtools:
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not Path("D:/work/project/service/wtools").exists(),
        reason="wtools 레포 없는 환경",
    )
    async def test_get_all_worktrees_wtools_repo(self):
        """실제 wtools 레포 경로로 get_all_worktrees 실행 — 타입 확인"""
        wtools_root = Path("D:/work/project/service/wtools")
        result = await svc.get_all_worktrees(repo_root=wtools_root)

        assert isinstance(result, WorktreeListResponse)
        assert isinstance(result.worktrees, list)
        assert isinstance(result.plan_only, list)
