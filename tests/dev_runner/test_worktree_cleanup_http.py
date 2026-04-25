from pathlib import Path
import subprocess
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.modules.dev_runner.schemas import (
    MainDirtyStatus,
    WorktreeCleanupResponse,
    WorktreeCleanupResult,
    WorktreeInfo,
    WorktreeListResponse,
)

pytestmark = [pytest.mark.http, pytest.mark.asyncio]


@pytest.fixture
async def client():
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _mock_worktree_response() -> WorktreeListResponse:
    return WorktreeListResponse(
        worktrees=[
            WorktreeInfo(
                branch="runner/t-cleanup-1",
                worktree_path="/repo/.worktrees/t-cleanup-1",
                created_at="2026-04-21 10:00:00 +0900",
                ahead=0,
                behind=2,
                locked=False,
                commit_count=0,
                commits=[],
                plan_file="docs/archive/test.md",
                plan_mtime="2026-04-21T10:00:00",
                is_test=True,
                plan_file_archived=True,
                cleanable=True,
            )
        ],
        plan_only=[],
        branch_unresolved=[],
        main_dirty=MainDirtyStatus(),
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(repo),
    ).stdout


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


def _add_worktree(repo: Path, branch: str, folder: str) -> Path:
    worktree = repo / ".worktrees" / folder
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", str(worktree), "-b", branch)
    return worktree


async def test_http_get_worktrees_v2_includes_new_flags(client):
    with patch(
        "app.modules.dev_runner.routes.worktrees.get_all_worktrees",
        new=AsyncMock(return_value=_mock_worktree_response()),
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2")

    assert resp.status_code == 200
    item = resp.json()["worktrees"][0]
    assert item["is_test"] is True
    assert item["plan_file_archived"] is True
    assert item["cleanable"] is True


async def test_http_get_worktrees_v2_marks_test_runner(client):
    response = WorktreeListResponse(
        worktrees=[
            WorktreeInfo(
                branch="runner/t-http-visible",
                worktree_path="/repo/.worktrees/t-http-visible",
                created_at="2026-04-21 10:00:00 +0900",
                ahead=0,
                behind=0,
                locked=False,
                commit_count=0,
                commits=[],
                plan_file=None,
                plan_mtime=None,
                is_test=True,
                cleanable=True,
            ),
            WorktreeInfo(
                branch="impl/http-visible",
                worktree_path="/repo/.worktrees/http-visible",
                created_at="2026-04-21 10:01:00 +0900",
                ahead=0,
                behind=0,
                locked=False,
                commit_count=0,
                commits=[],
                plan_file=None,
                plan_mtime=None,
                is_test=False,
                cleanable=True,
            ),
        ],
        plan_only=[],
        branch_unresolved=[],
        main_dirty=MainDirtyStatus(),
    )

    with patch(
        "app.modules.dev_runner.routes.worktrees.get_all_worktrees",
        new=AsyncMock(return_value=response),
    ):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2")

    assert resp.status_code == 200
    items = {item["branch"]: item for item in resp.json()["worktrees"]}
    assert items["runner/t-http-visible"]["is_test"] is True
    assert items["impl/http-visible"]["is_test"] is False


async def test_http_post_cleanup_calls_service(client):
    mock_response = WorktreeCleanupResponse(
        results=[
            WorktreeCleanupResult(
                branch="runner/t-cleanup-1",
                status="removed",
                worktree_removed=True,
                branch_removed=True,
            )
        ],
        summary={"requested": 1, "removed": 1, "skipped": 0, "failed": 0},
    )

    with patch(
        "app.modules.dev_runner.routes.worktrees.cleanup_worktrees",
        new=AsyncMock(return_value=mock_response),
    ) as mock_cleanup:
        resp = await client.post(
            "/api/v1/dev-runner/worktrees/cleanup",
            json={"branches": ["runner/t-cleanup-1"], "dry_run": False},
        )

    assert resp.status_code == 200
    assert resp.json()["summary"]["removed"] == 1
    mock_cleanup.assert_awaited_once_with(["runner/t-cleanup-1"], False)


async def test_http_post_cleanup_repo_id_scope(client):
    mock_response = WorktreeCleanupResponse(
        results=[],
        summary={"requested": 0, "removed": 0, "skipped": 0, "failed": 0, "not_found": 0, "timed_out": 0},
    )

    with patch(
        "app.modules.dev_runner.routes.worktrees._resolve_repo_root",
        return_value=Path("/repo-alt"),
    ), patch(
        "app.modules.dev_runner.routes.worktrees.cleanup_worktrees",
        new=AsyncMock(return_value=mock_response),
    ) as mock_cleanup:
        resp = await client.post(
            "/api/v1/dev-runner/worktrees/cleanup?repo_id=7",
            json={"branches": [], "dry_run": True},
        )

    assert resp.status_code == 200
    mock_cleanup.assert_awaited_once_with([], True, repo_root=Path("/repo-alt"))


async def test_http_post_cleanup_dry_run_does_not_remove(client, tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "runner/t-http-dry-run"
    worktree = _add_worktree(repo, branch, "t-http-dry-run")

    with patch(
        "app.modules.dev_runner.routes.worktrees._resolve_repo_root",
        return_value=repo,
    ):
        resp = await client.post(
            "/api/v1/dev-runner/worktrees/cleanup?repo_id=1",
            json={"branches": [branch], "dry_run": True},
        )

    assert resp.status_code == 200
    assert resp.json()["results"][0]["reason"] == "dry_run"
    listed = _git(repo, "worktree", "list", "--porcelain")
    assert branch in listed
    assert worktree.as_posix() in listed


async def test_http_post_cleanup_actual_removes(client, tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "runner/t-http-remove"
    _add_worktree(repo, branch, "t-http-remove")

    with patch(
        "app.modules.dev_runner.routes.worktrees._resolve_repo_root",
        return_value=repo,
    ):
        resp = await client.post(
            "/api/v1/dev-runner/worktrees/cleanup?repo_id=1",
            json={"branches": [branch], "dry_run": False},
        )

    assert resp.status_code == 200
    assert resp.json()["results"][0]["status"] == "removed"
    assert branch not in _git(repo, "worktree", "list", "--porcelain")
    assert branch not in _git(repo, "branch", "--list", branch)


async def test_http_post_cleanup_rejects_non_cleanable(client, tmp_path: Path):
    repo = _init_repo(tmp_path)
    locked_branch = "impl/http-locked"
    removable_branch = "runner/t-http-cleanable"
    locked_worktree = _add_worktree(repo, locked_branch, "http-locked")
    _git(repo, "worktree", "lock", str(locked_worktree))
    _add_worktree(repo, removable_branch, "t-http-cleanable")

    with patch(
        "app.modules.dev_runner.routes.worktrees._resolve_repo_root",
        return_value=repo,
    ):
        resp = await client.post(
            "/api/v1/dev-runner/worktrees/cleanup?repo_id=1",
            json={"branches": [locked_branch, removable_branch], "dry_run": False},
        )

    assert resp.status_code == 200
    body = resp.json()
    results = {item["branch"]: item for item in body["results"]}
    assert results[locked_branch]["status"] == "skipped"
    assert "locked" in results[locked_branch]["reason"]
    assert results[removable_branch]["status"] == "removed"


async def test_http_post_cleanup_returns_timeout_summary(client):
    mock_response = WorktreeCleanupResponse(
        results=[
            WorktreeCleanupResult(
                branch="runner/t-timeout",
                status="failed",
                reason="timeout after 30.0s",
                worktree_removed=False,
                branch_removed=False,
            )
        ],
        summary={"requested": 1, "removed": 0, "skipped": 0, "failed": 1, "not_found": 0, "timed_out": 1},
    )

    with patch(
        "app.modules.dev_runner.routes.worktrees.cleanup_worktrees",
        new=AsyncMock(return_value=mock_response),
    ):
        resp = await client.post(
            "/api/v1/dev-runner/worktrees/cleanup",
            json={"branches": ["runner/t-timeout"], "dry_run": False},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["timed_out"] == 1
    assert body["results"][0]["reason"] == "timeout after 30.0s"


async def test_http_post_cleanup_second_apply_reports_not_found(client, tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "runner/t-http-stale"
    _add_worktree(repo, branch, "t-http-stale")

    with patch(
        "app.modules.dev_runner.routes.worktrees._resolve_repo_root",
        return_value=repo,
    ):
        first = await client.post(
            "/api/v1/dev-runner/worktrees/cleanup?repo_id=1",
            json={"branches": [branch], "dry_run": False},
        )
        second = await client.post(
            "/api/v1/dev-runner/worktrees/cleanup?repo_id=1",
            json={"branches": [branch], "dry_run": False},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    body = second.json()
    assert body["summary"]["not_found"] == 1
    assert body["summary"]["skipped"] == 1
    assert body["results"][0]["reason"] == "worktree not found"
