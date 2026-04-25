import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.http, pytest.mark.asyncio]


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        env=env,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    return repo


def _add_worktree(repo: Path, branch: str) -> Path:
    worktree = repo / ".worktrees" / branch.replace("/", "-")
    _git(repo, "worktree", "add", "-b", branch, str(worktree))
    return worktree


def _commit_file(repo: Path, relative_path: str, message: str, date: str) -> None:
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{message}\n", encoding="utf-8")
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = date
    env["GIT_COMMITTER_DATE"] = date
    _git(repo, "add", relative_path, env=env)
    _git(repo, "commit", "-m", message, env=env)


@pytest.fixture
async def client():
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def test_commits_endpoint_right_returns_list(tmp_path: Path, client: AsyncClient):
    repo = _init_repo(tmp_path)
    branch = "impl/commits-list"
    worktree = _add_worktree(repo, branch)
    _commit_file(worktree, "app/feature.py", "feat: endpoint list", "2026-04-21 09:00:00 +0900")

    with patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo):
        resp = await client.get(f"/api/v1/dev-runner/worktrees/v2/commits?branch={branch}")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["message"] == "feat: endpoint list"
    assert data[0]["short_hash"]


async def test_commits_endpoint_error_unknown_branch_404(tmp_path: Path, client: AsyncClient):
    repo = _init_repo(tmp_path)

    with patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2/commits?branch=impl/missing")

    assert resp.status_code == 404


async def test_commits_endpoint_boundary_empty_branch_param(tmp_path: Path, client: AsyncClient):
    repo = _init_repo(tmp_path)

    with patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2/commits?branch=")

    assert resp.status_code == 422


async def test_flow_list_then_commits_by_branch(tmp_path: Path, client: AsyncClient):
    repo = _init_repo(tmp_path)
    branch = "impl/flow"
    worktree = _add_worktree(repo, branch)
    _commit_file(worktree, "app/feature.py", "feat: flow first", "2026-04-21 09:00:00 +0900")
    _commit_file(worktree, "app/feature2.py", "feat: flow second", "2026-04-21 10:00:00 +0900")

    with patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo):
        list_resp = await client.get("/api/v1/dev-runner/worktrees/v2")
        commits_resp = await client.get(f"/api/v1/dev-runner/worktrees/v2/commits?branch={branch}")

    assert list_resp.status_code == 200
    assert commits_resp.status_code == 200
    list_item = list_resp.json()["worktrees"][0]
    commits = commits_resp.json()
    assert list_item["branch"] == branch
    assert list_item["commit_count"] == 2
    assert len(commits) == 2
