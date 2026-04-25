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


def _write_plan(repo: Path, branch: str) -> None:
    plan_dir = repo / "docs" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / f"{branch.replace('/', '-')}.md").write_text(
        f"> branch: {branch}\n",
        encoding="utf-8",
    )


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


async def test_list_v2_right_returns_lite_schema(tmp_path: Path, client: AsyncClient):
    repo = _init_repo(tmp_path)
    branch = "impl/lite-schema"
    worktree = _add_worktree(repo, branch)
    _commit_file(worktree, "app/feature.py", "feat: lite schema", "2026-04-21 09:00:00 +0900")
    _write_plan(repo, branch)

    with patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2")

    assert resp.status_code == 200
    item = resp.json()["worktrees"][0]
    assert item["branch"] == branch
    assert item["commit_count"] == 1
    assert "commits" not in item


async def test_list_v2_correct_commit_count_matches_ahead(tmp_path: Path, client: AsyncClient):
    repo = _init_repo(tmp_path)
    branch = "impl/lite-count"
    worktree = _add_worktree(repo, branch)
    _commit_file(worktree, "app/one.py", "feat: one", "2026-04-21 09:00:00 +0900")
    _commit_file(worktree, "app/two.py", "feat: two", "2026-04-21 10:00:00 +0900")
    _write_plan(repo, branch)

    with patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2")

    assert resp.status_code == 200
    item = resp.json()["worktrees"][0]
    assert item["ahead"] == 2
    assert item["commit_count"] == item["ahead"]


async def test_list_v2_correct_created_at_preserved(tmp_path: Path, client: AsyncClient):
    repo = _init_repo(tmp_path)
    branch = "impl/lite-created-at"
    worktree = _add_worktree(repo, branch)
    _commit_file(worktree, "app/first.py", "feat: first", "2026-04-21 08:00:00 +0900")
    _commit_file(worktree, "app/second.py", "feat: second", "2026-04-21 10:00:00 +0900")
    _write_plan(repo, branch)

    with patch("app.modules.dev_runner.routes.worktrees._resolve_repo_root", return_value=repo):
        resp = await client.get("/api/v1/dev-runner/worktrees/v2")

    assert resp.status_code == 200
    item = resp.json()["worktrees"][0]
    assert item["created_at"] == "2026-04-21 08:00:00 +0900"
