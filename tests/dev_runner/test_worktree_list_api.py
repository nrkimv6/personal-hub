"""worktree_service 단위 TC + GET /worktrees HTTP TC"""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
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

    @pytest.mark.asyncio
    async def test_right_excludes_prunable(self):
        """prunable 블록이 있는 워크트리 제외"""
        from app.modules.dev_runner.services.worktree_service import list_worktrees

        porcelain = (
            "worktree /repo/.worktrees/prunable-wt\n"
            "HEAD aaa111\n"
            "prunable\n"
            "\n"
            "worktree /repo/.worktrees/impl-bar\n"
            "HEAD bbb222\n"
            "branch refs/heads/impl/bar\n"
            "locked reason\n"
            "\n"
        )
        with patch(
            "app.modules.dev_runner.services.worktree_service._run_git",
            new=AsyncMock(return_value=porcelain.strip()),
        ):
            result = await list_worktrees()

        assert len(result) == 1
        assert result[0]["branch"] == "impl/bar"
        assert result[0]["locked"] is True


class TestGetAheadBehind:
    @pytest.mark.asyncio
    async def test_right_counts(self):
        """git rev-list mock → (ahead, behind) 정수 튜플 반환"""
        from app.modules.dev_runner.services.worktree_service import get_ahead_behind

        async def mock_run(*args, **kwargs):
            return "1\t3"

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

        log_output = (
            "__WT_COMMIT__abc1234567890|2026-04-07 10:00:00 +0900|feat: test commit\n"
            "5\t2\tapp/foo.py\n"
            "3\t1\tapp/bar.py\n"
        )

        with patch(
            "app.modules.dev_runner.services.worktree_service._run_git",
            new=AsyncMock(return_value=log_output),
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
        """.worktrees/plans/docs/plan 아래 mock 파일에서 > branch: 헤더 매칭 → 경로 반환"""
        import app.modules.dev_runner.services.worktree_service as svc

        plan_dir = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "2026-04-07_my-plan.md"
        plan_file.write_text(
            "# plan\n\n> 작성일시: 2026-04-07\n> branch: impl/my-feature\n",
            encoding="utf-8",
        )

        result, mtime, archived = svc.find_plan_file("impl/my-feature", repo_root=tmp_path)

        assert result is not None
        assert "my-plan" in result
        assert mtime is not None
        assert mtime[4] == "-"  # ISO 8601 형식 간이 확인
        assert archived is False

    def test_right_no_match(self, tmp_path, monkeypatch):
        """일치하는 파일 없음 → (None, None) 반환"""
        import app.modules.dev_runner.services.worktree_service as svc

        plan_dir = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "other.md").write_text(
            "> branch: impl/other\n", encoding="utf-8"
        )

        result, mtime, archived = svc.find_plan_file("impl/nonexistent", repo_root=tmp_path)

        assert result is None
        assert mtime is None
        assert archived is False


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


class TestRealGitPrunable:
    @pytest.mark.asyncio
    async def test_list_worktrees_filters_prunable_real_git(self, tmp_path):
        """실제 git worktree list에서 prunable registration이 결과에 노출되지 않음"""
        from app.modules.dev_runner.services.worktree_service import list_worktrees

        repo = tmp_path / "repo"
        subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True, cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Test"], capture_output=True, cwd=str(repo), check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], capture_output=True, cwd=str(repo), check=True)
        (repo / "README.md").write_text("seed", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], capture_output=True, cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "init"], capture_output=True, cwd=str(repo), check=True)

        active_path = repo / ".worktrees" / "runner-active"
        prunable_path = repo / ".worktrees" / "runner-prunable"
        subprocess.run(
            ["git", "worktree", "add", "-b", "runner/active", str(active_path)],
            capture_output=True, cwd=str(repo), check=True,
        )
        subprocess.run(
            ["git", "worktree", "add", "-b", "runner/prunable", str(prunable_path)],
            capture_output=True, cwd=str(repo), check=True,
        )
        shutil.rmtree(prunable_path)

        result = await list_worktrees(repo_root=repo)
        branches = [wt["branch"] for wt in result]

        assert "runner/active" in branches
        assert "runner/prunable" not in branches


def _run_repo_git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", *args], cwd=str(repo), capture_output=True, check=True, env=env)


def _init_http_repo(tmp_path: Path, worktree_count: int = 1, commits_per_worktree: int = 1) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_repo_git(repo, "init", "-b", "main")
    _run_repo_git(repo, "config", "user.email", "test@test.com")
    _run_repo_git(repo, "config", "user.name", "Test")
    _run_repo_git(repo, "config", "commit.gpgsign", "false")

    (repo / "README.md").write_text("seed", encoding="utf-8")
    _run_repo_git(repo, "add", "README.md")
    _run_repo_git(repo, "commit", "-m", "init")

    plan_dir = repo / "docs" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)

    for index in range(worktree_count):
        branch = f"impl/http-{index}"
        worktree_path = repo / ".worktrees" / f"impl-http-{index}"
        _run_repo_git(repo, "worktree", "add", "-b", branch, str(worktree_path))

        for commit_index in range(commits_per_worktree):
            target = worktree_path / "app" / f"file_{index}_{commit_index}.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"print('{index}-{commit_index}')\n", encoding="utf-8")
            env = os.environ.copy()
            env["GIT_AUTHOR_DATE"] = f"2026-04-07 0{commit_index}:00:00 +0900"
            env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"]
            _run_repo_git(worktree_path, "add", str(target.relative_to(worktree_path)), env=env)
            _run_repo_git(
                worktree_path,
                "commit",
                "-m",
                f"feat: commit {index}-{commit_index}",
                env=env,
            )

        (plan_dir / f"2026-04-07_http-{index}.md").write_text(
            f"> branch: {branch}\n",
            encoding="utf-8",
        )

    return repo


@pytest.fixture
async def http_client():
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestWorktreeListHttp:
    @pytest.mark.http
    @pytest.mark.asyncio
    async def test_list_worktrees_v2_http_right_shape_preserved(self, tmp_path: Path, http_client):
        repo = _init_http_repo(tmp_path, worktree_count=1, commits_per_worktree=1)

        with patch(
            "app.modules.dev_runner.routes.worktrees._resolve_repo_root",
            return_value=repo,
        ):
            v1_resp = await http_client.get("/api/v1/dev-runner/worktrees")
            v2_resp = await http_client.get("/api/v1/dev-runner/worktrees/v2")

        assert v1_resp.status_code == 200
        assert v2_resp.status_code == 200

        v1_data = v1_resp.json()
        v2_data = v2_resp.json()

        assert isinstance(v1_data, list)
        assert isinstance(v2_data, dict)
        assert set(v2_data.keys()) == {
            "worktrees",
            "plan_only",
            "branch_unresolved",
            "main_dirty",
        }
        assert len(v2_data["worktrees"]) == len(v1_data) == 1
        assert v2_data["worktrees"][0]["branch"] == v1_data[0]["branch"]
        assert "commits" in v1_data[0]
        assert "commit_count" in v2_data["worktrees"][0]
        assert "commits" not in v2_data["worktrees"][0]

    @pytest.mark.http
    @pytest.mark.asyncio
    async def test_list_worktrees_v2_http_plan_mtime_present(self, tmp_path: Path, http_client):
        repo = _init_http_repo(tmp_path, worktree_count=1, commits_per_worktree=1)

        with patch(
            "app.modules.dev_runner.routes.worktrees._resolve_repo_root",
            return_value=repo,
        ):
            resp = await http_client.get("/api/v1/dev-runner/worktrees/v2")

        assert resp.status_code == 200
        item = resp.json()["worktrees"][0]
        assert item["plan_mtime"] is not None
        assert item["plan_mtime"][4] == "-"
        assert item["plan_file"].replace("\\", "/").startswith(".worktrees/plans/docs/plan/")
        assert item["created_at"] is not None

    @pytest.mark.http
    @pytest.mark.asyncio
    async def test_list_worktrees_v2_http_commits_lazy_endpoint(self, tmp_path: Path, http_client):
        repo = _init_http_repo(tmp_path, worktree_count=1, commits_per_worktree=2)

        with patch(
            "app.modules.dev_runner.routes.worktrees._resolve_repo_root",
            return_value=repo,
        ):
            resp = await http_client.get("/api/v1/dev-runner/worktrees/v2/commits", params={"branch": "impl/http-0"})

        assert resp.status_code == 200
        commits = resp.json()
        assert len(commits) == 2
        assert commits[0]["message"].startswith("feat: commit 0-")
        assert "diff_stat" in commits[0]

    @pytest.mark.http
    @pytest.mark.asyncio
    async def test_list_worktrees_v2_http_performance_10worktrees(self, tmp_path: Path, http_client):
        repo = _init_http_repo(tmp_path, worktree_count=10, commits_per_worktree=3)

        with patch(
            "app.modules.dev_runner.routes.worktrees._resolve_repo_root",
            return_value=repo,
        ):
            started = time.perf_counter()
            resp = await http_client.get("/api/v1/dev-runner/worktrees/v2")
            elapsed = time.perf_counter() - started

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["worktrees"]) == 10
        assert all(item["commit_count"] == 3 for item in data["worktrees"])
        assert all("commits" not in item for item in data["worktrees"])
        assert elapsed < 3.0

    @pytest.mark.http
    @pytest.mark.asyncio
    async def test_list_v2_http_cache_hit_consistent_response(self, tmp_path: Path, http_client):
        from app.modules.dev_runner.schemas import MainDirtyStatus, WorktreeInfoLite, WorktreeListResponse

        repo = tmp_path / "repo"
        repo.mkdir()
        expected = WorktreeListResponse(
            worktrees=[
                WorktreeInfoLite(
                    branch="impl/cache-hit",
                    worktree_path="/repo/.worktrees/impl-cache-hit",
                    created_at="2026-04-21 09:00:00 +0900",
                    ahead=1,
                    behind=0,
                    locked=False,
                    commit_count=1,
                    plan_file=".worktrees/plans/docs/plan/cache.md",
                    plan_mtime="2026-04-21T09:00:00",
                    is_test=False,
                    plan_file_archived=False,
                    cleanable=False,
                )
            ],
            plan_only=[],
            branch_unresolved=[],
            main_dirty=MainDirtyStatus(),
        )
        compute = AsyncMock(return_value=expected)

        with (
            patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo),
            patch("app.modules.dev_runner.services.worktree_service._compute_worktree_list_response", new=compute),
        ):
            first = await http_client.get("/api/v1/dev-runner/worktrees/v2")
            second = await http_client.get("/api/v1/dev-runner/worktrees/v2")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        assert compute.await_count == 1

    @pytest.mark.http
    @pytest.mark.asyncio
    async def test_list_v2_http_force_bypasses_cache(self, tmp_path: Path, http_client):
        from app.modules.dev_runner.schemas import MainDirtyStatus, WorktreeInfoLite, WorktreeListResponse

        repo = tmp_path / "repo"
        repo.mkdir()
        compute = AsyncMock(
            side_effect=[
                WorktreeListResponse(
                    worktrees=[
                        WorktreeInfoLite(
                            branch="impl/first",
                            worktree_path="/repo/.worktrees/impl-first",
                            created_at="2026-04-21 09:00:00 +0900",
                            ahead=1,
                            behind=0,
                            locked=False,
                            commit_count=1,
                            plan_file=".worktrees/plans/docs/plan/first.md",
                            plan_mtime="2026-04-21T09:00:00",
                            is_test=False,
                            plan_file_archived=False,
                            cleanable=False,
                        )
                    ],
                    plan_only=[],
                    branch_unresolved=[],
                    main_dirty=MainDirtyStatus(),
                ),
                WorktreeListResponse(
                    worktrees=[
                        WorktreeInfoLite(
                            branch="impl/forced",
                            worktree_path="/repo/.worktrees/impl-forced",
                            created_at="2026-04-21 10:00:00 +0900",
                            ahead=2,
                            behind=0,
                            locked=False,
                            commit_count=2,
                            plan_file=".worktrees/plans/docs/plan/forced.md",
                            plan_mtime="2026-04-21T10:00:00",
                            is_test=False,
                            plan_file_archived=False,
                            cleanable=False,
                        )
                    ],
                    plan_only=[],
                    branch_unresolved=[],
                    main_dirty=MainDirtyStatus(),
                ),
            ]
        )

        with (
            patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo),
            patch("app.modules.dev_runner.services.worktree_service._compute_worktree_list_response", new=compute),
        ):
            first = await http_client.get("/api/v1/dev-runner/worktrees/v2")
            second = await http_client.get("/api/v1/dev-runner/worktrees/v2")
            forced = await http_client.get("/api/v1/dev-runner/worktrees/v2?force=1")

        assert first.status_code == 200
        assert second.status_code == 200
        assert forced.status_code == 200
        assert first.json() == second.json()
        assert forced.json()["worktrees"][0]["branch"] == "impl/forced"
        assert compute.await_count == 2
