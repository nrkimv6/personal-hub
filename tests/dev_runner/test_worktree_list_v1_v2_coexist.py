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


async def test_v1_returns_full_commits(tmp_path: Path, client: AsyncClient):
    repo = _init_repo(tmp_path)
    branch = "impl/full"
    worktree = _add_worktree(repo, branch)
    _commit_file(worktree, "app/full.py", "feat: full", "2026-04-21 09:00:00 +0900")

    with patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo):
        resp = await client.get("/api/v1/dev-runner/worktrees")

    assert resp.status_code == 200
    item = resp.json()[0]
    assert "commits" in item
    assert len(item["commits"]) == 1


async def test_v2_excludes_commits(tmp_path: Path, client: AsyncClient):
    repo = _init_repo(tmp_path)
    branch = "impl/lite"
    worktree = _add_worktree(repo, branch)
    _commit_file(worktree, "app/lite.py", "feat: lite", "2026-04-21 09:00:00 +0900")

    with patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2")

    assert resp.status_code == 200
    item = resp.json()["worktrees"][0]
    assert "commit_count" in item
    assert "commits" not in item


async def test_v2_commits_endpoint_matches_v1_hashes(tmp_path: Path, client: AsyncClient):
    repo = _init_repo(tmp_path)
    branch = "impl/coexist"
    worktree = _add_worktree(repo, branch)
    _commit_file(worktree, "app/one.py", "feat: one", "2026-04-21 09:00:00 +0900")
    _commit_file(worktree, "app/two.py", "feat: two", "2026-04-21 10:00:00 +0900")

    with patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo):
        v1_resp = await client.get("/api/v1/dev-runner/worktrees")
        commits_resp = await client.get(f"/api/v1/dev-runner/worktrees/v2/commits?branch={branch}")

    assert v1_resp.status_code == 200
    assert commits_resp.status_code == 200
    v1_hashes = {commit["hash"] for commit in v1_resp.json()[0]["commits"]}
    v2_hashes = {commit["hash"] for commit in commits_resp.json()}
    assert v1_hashes == v2_hashes


async def test_v1_v2_commits_zero_commit_branch_consistent(tmp_path: Path, client: AsyncClient):
    repo = _init_repo(tmp_path)
    branch = "impl/empty"
    _add_worktree(repo, branch)

    with patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo):
        v1_resp = await client.get("/api/v1/dev-runner/worktrees")
        v2_resp = await client.get("/api/v1/dev-runner/worktrees/v2")
        commits_resp = await client.get(f"/api/v1/dev-runner/worktrees/v2/commits?branch={branch}")

    assert v1_resp.status_code == 200
    assert v2_resp.status_code == 200
    assert commits_resp.status_code == 200
    assert v1_resp.json()[0]["commits"] == []
    assert v2_resp.json()["worktrees"][0]["commit_count"] == 0
    assert v2_resp.json()["worktrees"][0]["created_at"] is None
    assert commits_resp.json() == []
