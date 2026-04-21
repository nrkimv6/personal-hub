import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.modules.dev_runner.services import worktree_service as svc


@pytest.mark.asyncio
async def test_cleanup_worktrees_dry_run_returns_targets_only(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        svc,
        "list_worktrees",
        AsyncMock(return_value=[{"branch": "runner/t-test-1", "worktree_path": str(tmp_path / "wt"), "locked": False}]),
    )
    monkeypatch.setattr(svc, "get_ahead_behind", AsyncMock(return_value=(0, 3)))
    monkeypatch.setattr(svc, "find_plan_file", lambda *_args, **_kwargs: (None, None, False))

    async def _unexpected(*_args, **_kwargs):
        raise AssertionError("_run_git_exec should not be called during dry-run")

    monkeypatch.setattr(svc, "_run_git_exec", _unexpected)

    result = await svc.cleanup_worktrees(["runner/t-test-1"], dry_run=True, repo_root=tmp_path)

    assert result.summary == {"requested": 1, "removed": 0, "skipped": 1, "failed": 0}
    assert result.results[0].reason == "dry_run"


@pytest.mark.asyncio
async def test_cleanup_worktrees_removes_worktree_and_branch(monkeypatch, tmp_path: Path):
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        svc,
        "list_worktrees",
        AsyncMock(return_value=[{"branch": "runner/t-test-2", "worktree_path": str(tmp_path / "wt"), "locked": False}]),
    )
    monkeypatch.setattr(svc, "get_ahead_behind", AsyncMock(return_value=(0, 0)))
    monkeypatch.setattr(svc, "find_plan_file", lambda *_args, **_kwargs: (None, None, False))

    async def _fake_git_exec(*args: str, repo_root: Path):
        calls.append(args)
        return 0, "", ""

    monkeypatch.setattr(svc, "_run_git_exec", _fake_git_exec)

    result = await svc.cleanup_worktrees(["runner/t-test-2"], dry_run=False, repo_root=tmp_path)

    assert result.summary == {"requested": 1, "removed": 1, "skipped": 0, "failed": 0}
    assert calls[0][:3] == ("worktree", "remove", "--force")
    assert calls[1][:2] == ("branch", "-D")


@pytest.mark.asyncio
async def test_cleanup_worktrees_skips_locked_and_ahead(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        svc,
        "list_worktrees",
        AsyncMock(
            return_value=[
                {"branch": "runner/t-locked", "worktree_path": str(tmp_path / "locked"), "locked": True},
                {"branch": "runner/t-ahead", "worktree_path": str(tmp_path / "ahead"), "locked": False},
            ]
        ),
    )

    async def _ahead(branch: str, repo_root: Path):
        if branch == "runner/t-locked":
            return 0, 0
        return 2, 0

    monkeypatch.setattr(svc, "get_ahead_behind", _ahead)
    monkeypatch.setattr(svc, "find_plan_file", lambda *_args, **_kwargs: (None, None, False))
    monkeypatch.setattr(svc, "_run_git_exec", AsyncMock())

    result = await svc.cleanup_worktrees(
        ["runner/t-locked", "runner/t-ahead"],
        dry_run=False,
        repo_root=tmp_path,
    )

    assert result.summary == {"requested": 2, "removed": 0, "skipped": 2, "failed": 0}
    assert "locked" in result.results[0].reason
    assert "ahead=2" in result.results[1].reason


@pytest.mark.asyncio
async def test_cleanup_worktrees_reports_git_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        svc,
        "list_worktrees",
        AsyncMock(return_value=[{"branch": "runner/t-fail", "worktree_path": str(tmp_path / "wt"), "locked": False}]),
    )
    monkeypatch.setattr(svc, "get_ahead_behind", AsyncMock(return_value=(0, 0)))
    monkeypatch.setattr(svc, "find_plan_file", lambda *_args, **_kwargs: (None, None, False))

    async def _fake_git_exec(*args: str, repo_root: Path):
        if args[:2] == ("worktree", "remove"):
            return 1, "", "fatal remove failed"
        return 0, "", ""

    monkeypatch.setattr(svc, "_run_git_exec", _fake_git_exec)

    result = await svc.cleanup_worktrees(["runner/t-fail"], dry_run=False, repo_root=tmp_path)

    assert result.summary == {"requested": 1, "removed": 0, "skipped": 0, "failed": 1}
    assert "fatal remove failed" in result.results[0].reason


@pytest.mark.asyncio
async def test_cleanup_worktrees_concurrent_calls_serialized(monkeypatch, tmp_path: Path):
    order: list[str] = []
    first_started = asyncio.Event()
    allow_first_finish = asyncio.Event()

    monkeypatch.setattr(
        svc,
        "list_worktrees",
        AsyncMock(
            return_value=[
                {"branch": "runner/t-serial-1", "worktree_path": str(tmp_path / "wt1"), "locked": False},
                {"branch": "runner/t-serial-2", "worktree_path": str(tmp_path / "wt2"), "locked": False},
            ]
        ),
    )
    monkeypatch.setattr(svc, "get_ahead_behind", AsyncMock(return_value=(0, 0)))
    monkeypatch.setattr(svc, "find_plan_file", lambda *_args, **_kwargs: (None, None, False))

    async def _fake_git_exec(*args: str, repo_root: Path):
        branch = args[-1]
        if args[:3] == ("worktree", "remove", "--force"):
            order.append(f"start:{branch}")
            if branch.endswith("wt1"):
                first_started.set()
                await allow_first_finish.wait()
            order.append(f"end:{branch}")
        return 0, "", ""

    monkeypatch.setattr(svc, "_run_git_exec", _fake_git_exec)

    task1 = asyncio.create_task(
        svc.cleanup_worktrees(["runner/t-serial-1"], dry_run=False, repo_root=tmp_path)
    )
    await first_started.wait()

    task2 = asyncio.create_task(
        svc.cleanup_worktrees(["runner/t-serial-2"], dry_run=False, repo_root=tmp_path)
    )

    await asyncio.sleep(0.05)
    assert order == [f"start:{tmp_path / 'wt1'}"]

    allow_first_finish.set()
    await asyncio.gather(task1, task2)

    assert order == [
        f"start:{tmp_path / 'wt1'}",
        f"end:{tmp_path / 'wt1'}",
        f"start:{tmp_path / 'wt2'}",
        f"end:{tmp_path / 'wt2'}",
    ]
