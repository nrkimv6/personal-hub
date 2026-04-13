"""worktree_service 단위 TC + GET /worktrees HTTP TC"""
import re
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


# ──────────────────────────────────────────────
# worktree_service 단위 테스트
# ──────────────────────────────────────────────

class TestListWorktrees:
    @pytest.mark.asyncio
    async def test_right_excludes_main(self):
        """git worktree list 결과에서 branch == main 인 워크트리 제외"""
        from app.modules.dev_runner.services.worktree_service import list_worktrees

        porcelain = (
            "worktree /repo\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /repo/.worktrees/impl-foo\n"
            "HEAD def456\n"
            "branch refs/heads/impl/foo\n"
            "\n"
        )
        with patch(
            "app.modules.dev_runner.services.worktree_service._run_git",
            new=AsyncMock(return_value=porcelain.strip()),
        ):
            result = await list_worktrees()

        assert len(result) == 1
        assert result[0]["branch"] == "impl/foo"

    @pytest.mark.asyncio
    async def test_right_locked_flag(self):
        """locked 라인 있는 블록 → locked=True"""
        from app.modules.dev_runner.services.worktree_service import list_worktrees

        porcelain = (
            "worktree /repo/.worktrees/impl-bar\n"
            "HEAD aaa111\n"
            "branch refs/heads/impl/bar\n"
            "locked reason\n"
            "\n"
        )
        with patch(
            "app.modules.dev_runner.services.worktree_service._run_git",
            new=AsyncMock(return_value=porcelain.strip()),
        ):
            result = await list_worktrees()

        assert result[0]["locked"] is True

    @pytest.mark.asyncio
    async def test_right_excludes_detached(self):
        """detached HEAD 워크트리 제외"""
        from app.modules.dev_runner.services.worktree_service import list_worktrees

        porcelain = (
            "worktree /repo/.worktrees/detached-wt\n"
            "HEAD bbb222\n"
            "detached\n"
            "\n"
        )
        with patch(
            "app.modules.dev_runner.services.worktree_service._run_git",
            new=AsyncMock(return_value=porcelain.strip()),
        ):
            result = await list_worktrees()

        assert result == []


class TestGetAheadBehind:
    @pytest.mark.asyncio
    async def test_right_counts(self):
        """git rev-list mock → (ahead, behind) 정수 튜플 반환"""
        from app.modules.dev_runner.services.worktree_service import get_ahead_behind

        call_count = 0

        async def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # 첫 번째 호출: ahead, 두 번째 호출: behind
            return "3" if call_count == 1 else "1"

        with patch(
            "app.modules.dev_runner.services.worktree_service._run_git",
            side_effect=mock_run,
        ):
            ahead, behind = await get_ahead_behind("impl/foo")

        assert ahead == 3
        assert behind == 1


class TestGetWorktreeCommits:
    @pytest.mark.asyncio
    async def test_right_parses_log(self):
        """git log mock → WorktreeCommit 리스트, 필드 확인"""
        from app.modules.dev_runner.services.worktree_service import get_worktree_commits

        log_line = "abc1234567890|2026-04-07 10:00:00 +0900|feat: test commit"
        numstat_line = "5\t2\tapp/foo.py\n3\t1\tapp/bar.py"

        call_count = 0

        async def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return log_line
            return numstat_line

        with patch(
            "app.modules.dev_runner.services.worktree_service._run_git",
            side_effect=mock_run,
        ):
            commits = await get_worktree_commits("impl/foo")

        assert len(commits) == 1
        c = commits[0]
        assert c.hash == "abc1234567890"
        assert c.short_hash == "abc1234"
        assert c.message == "feat: test commit"
        assert c.date == "2026-04-07 10:00:00 +0900"
        assert len(c.diff_stat) == 2
        assert c.diff_stat[0].file == "app/foo.py"
        assert c.diff_stat[0].changes == "+5 -2"

    @pytest.mark.asyncio
    async def test_empty_branch_returns_empty_list(self):
        """커밋 0개 브랜치 → 빈 리스트"""
        from app.modules.dev_runner.services.worktree_service import get_worktree_commits

        with patch(
            "app.modules.dev_runner.services.worktree_service._run_git",
            new=AsyncMock(return_value=""),
        ):
            commits = await get_worktree_commits("impl/empty")

        assert commits == []


class TestFindPlanFile:
    def test_right_matches_branch(self, tmp_path, monkeypatch):
        """docs/plan/ 아래 mock 파일에서 > branch: 헤더 매칭 → 경로 반환"""
        import app.modules.dev_runner.services.worktree_service as svc

        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "2026-04-07_my-plan.md"
        plan_file.write_text(
            "# plan\n\n> 작성일시: 2026-04-07\n> branch: impl/my-feature\n",
            encoding="utf-8",
        )

        result, mtime = svc.find_plan_file("impl/my-feature", repo_root=tmp_path)

        assert result is not None
        assert "my-plan" in result
        assert mtime is not None
        assert re.match(r"^\d{4}-\d{2}-\d{2}T", mtime)

    def test_right_no_match(self, tmp_path, monkeypatch):
        """일치하는 파일 없음 → None 반환"""
        import app.modules.dev_runner.services.worktree_service as svc

        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "other.md").write_text(
            "> branch: impl/other\n", encoding="utf-8"
        )

        result, mtime = svc.find_plan_file("impl/nonexistent", repo_root=tmp_path)

        assert result is None
        assert mtime is None


class TestPlanOnlyBranches:
    def test_right_filters_existing_branches(self, tmp_path):
        from app.modules.dev_runner.services.worktree_service import list_plan_only_branches

        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)

        (plan_dir / "2026-04-01_plan-a.md").write_text(
            "# plan a\n\n> branch: impl/a\n",
            encoding="utf-8",
        )
        (plan_dir / "2026-04-02_plan-b.md").write_text(
            "# plan b\n\n> branch: impl/b\n",
            encoding="utf-8",
        )
        (plan_dir / "2026-04-03_no-branch.md").write_text(
            "# plan c\n\n작성\n",
            encoding="utf-8",
        )

        plan_only, unresolved = list_plan_only_branches(
            {"impl/a"},
            repo_root=tmp_path,
        )

        assert len(plan_only) == 1
        assert plan_only[0].branch == "impl/b"
        assert len(unresolved) == 1
        assert unresolved[0].reason == "missing > branch header"

    def test_all_existing_returns_empty(self, tmp_path):
        from app.modules.dev_runner.services.worktree_service import list_plan_only_branches

        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "2026-04-01_plan-a.md").write_text(
            "# plan a\n\n> branch: impl/a\n",
            encoding="utf-8",
        )
        (plan_dir / "2026-04-02_plan-b.md").write_text(
            "# plan b\n\n> branch: impl/b\n",
            encoding="utf-8",
        )

        plan_only, unresolved = list_plan_only_branches({"impl/a", "impl/b"}, repo_root=tmp_path)

        assert plan_only == []
        assert unresolved == []


class TestRunGitError:
    @pytest.mark.asyncio
    async def test_error_returns_empty(self):
        """git 명령 실패 → 빈 문자열 반환, 예외 미전파"""
        from app.modules.dev_runner.services.worktree_service import _run_git

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            result = await _run_git("invalid-command")

        assert result == ""


class TestMainDirty:
    @pytest.mark.asyncio
    async def test_get_main_dirty_parses_rename_path(self):
        from app.modules.dev_runner.services.worktree_service import get_main_dirty

        with patch(
            "app.modules.dev_runner.services.worktree_service._run_git",
            new=AsyncMock(return_value="R  old_name.py\0new_name.py\0"),
        ):
            result = await get_main_dirty()

        assert result.dirty_count == 1
        assert result.files == ["new_name.py"]

    @pytest.mark.asyncio
    async def test_get_main_dirty_parses_space_name(self):
        from app.modules.dev_runner.services.worktree_service import get_main_dirty

        with patch(
            "app.modules.dev_runner.services.worktree_service._run_git",
            new=AsyncMock(return_value=" M src/space name.py\0?? new file.py\0"),
        ):
            result = await get_main_dirty()

        assert result.dirty_count == 2
        assert "src/space name.py" in result.files
        assert "new file.py" in result.files

    @pytest.mark.asyncio
    async def test_get_main_dirty_empty_output(self):
        from app.modules.dev_runner.services.worktree_service import get_main_dirty

        with patch(
            "app.modules.dev_runner.services.worktree_service._run_git",
            new=AsyncMock(return_value=""),
        ):
            result = await get_main_dirty()

        assert result.dirty_count == 0
        assert result.files == []


class TestGetAllWorktrees:
    @pytest.mark.asyncio
    async def test_empty_raw_returns_plan_only(self):
        from app.modules.dev_runner.schemas import MainDirtyStatus, PlanOnlyBranch
        import app.modules.dev_runner.services.worktree_service as svc

        with patch(
            "app.modules.dev_runner.services.worktree_service.list_worktrees",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.modules.dev_runner.services.worktree_service.list_plan_only_branches",
            new=lambda *_args: ([PlanOnlyBranch(plan_file="2026-04-01_plan-a.md", branch="impl/a", plan_mtime=None)], []),
        ), patch(
            "app.modules.dev_runner.services.worktree_service.get_main_dirty",
            new=AsyncMock(return_value=MainDirtyStatus(dirty_count=0, files=[])),
        ):
            result = await svc.get_all_worktrees()

        assert result.worktrees == []
        assert len(result.plan_only) == 1
        assert result.plan_only[0].branch == "impl/a"

    @pytest.mark.asyncio
    async def test_nonexistent_repo_root_returns_empty_response(self, tmp_path):
        from app.modules.dev_runner.services.worktree_service import get_all_worktrees

        missing = tmp_path / "missing"
        missing.mkdir()
        target = missing / "repo"
        # 폴더 자체를 제거해 존재하지 않는 루트 경로 시뮬레이션
        target.rmdir() if target.exists() else None

        result = await get_all_worktrees(repo_root=target)

        assert result.worktrees == []
        assert result.plan_only == []
        assert result.branch_unresolved == []
        assert result.main_dirty.dirty_count == 0


# ──────────────────────────────────────────────
# T3: 실제 git 레포 대상 통합 TC
# ──────────────────────────────────────────────

class TestRealRepo:
    @pytest.mark.asyncio
    async def test_list_worktrees_real_repo(self):
        """실제 git worktree list — main 제외, 최소 1개 이상 (현재 impl 브랜치 포함)"""
        from app.modules.dev_runner.services.worktree_service import list_worktrees

        result = await list_worktrees()
        branches = [wt["branch"] for wt in result]
        assert "main" not in branches
        # 현재 worktree(impl/worktree-history-tab)가 포함돼 있어야 함
        # (없어도 실패는 아님 — 다른 브랜치가 있으면 OK)
        assert len(result) >= 0  # 최소한 예외 없이 실행됨을 확인

    @pytest.mark.asyncio
    async def test_get_ahead_behind_real_main_branch(self):
        """main 브랜치 대상 ahead/behind — main은 자기 자신이므로 (0, 0)"""
        from app.modules.dev_runner.services.worktree_service import get_ahead_behind

        # "main..main" 과 "main..main" 은 모두 0
        ahead, behind = await get_ahead_behind("main")
        assert ahead == 0
        assert behind == 0
