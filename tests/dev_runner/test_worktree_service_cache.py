import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import app.modules.dev_runner.services.worktree_service as svc
from app.modules.dev_runner.schemas import MainDirtyStatus, WorktreeInfoLite, WorktreeListResponse


def _response(branch: str) -> WorktreeListResponse:
    return WorktreeListResponse(
        worktrees=[
            WorktreeInfoLite(
                branch=branch,
                worktree_path=f"/repo/.worktrees/{branch.replace('/', '-')}",
                created_at="2026-04-21 09:00:00 +0900",
                ahead=1,
                behind=0,
                locked=False,
                commit_count=1,
                plan_file="docs/plan/example.md",
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


@pytest.mark.asyncio
async def test_cache_right_hit_returns_cached_response(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    compute = AsyncMock(return_value=_response("impl/cache-hit"))

    with patch.object(svc, "_compute_worktree_list_response", new=compute):
        first = await svc.get_all_worktrees(repo_root=repo_root, use_cache=True, cache_repo_id=7)
        second = await svc.get_all_worktrees(repo_root=repo_root, use_cache=True, cache_repo_id=7)

    assert compute.await_count == 1
    assert first == second
    assert first is not second


@pytest.mark.asyncio
async def test_cache_boundary_ttl_expiry_recomputes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    current = [100.0]
    monkeypatch.setattr(svc.time, "monotonic", lambda: current[0])
    compute = AsyncMock(side_effect=[_response("impl/first"), _response("impl/second")])

    with patch.object(svc, "_compute_worktree_list_response", new=compute):
        first = await svc.get_all_worktrees(repo_root=repo_root, use_cache=True, cache_repo_id=9)
        current[0] = 104.0
        second = await svc.get_all_worktrees(repo_root=repo_root, use_cache=True, cache_repo_id=9)

    assert compute.await_count == 2
    assert first.worktrees[0].branch == "impl/first"
    assert second.worktrees[0].branch == "impl/second"


@pytest.mark.asyncio
async def test_cache_error_force_flag_bypasses(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    compute = AsyncMock(side_effect=[_response("impl/cached"), _response("impl/forced")])

    with patch.object(svc, "_compute_worktree_list_response", new=compute):
        cached = await svc.get_all_worktrees(repo_root=repo_root, use_cache=True, cache_repo_id=1)
        forced = await svc.get_all_worktrees(
            repo_root=repo_root,
            use_cache=True,
            cache_repo_id=1,
            force=True,
        )

    assert compute.await_count == 2
    assert cached.worktrees[0].branch == "impl/cached"
    assert forced.worktrees[0].branch == "impl/forced"


@pytest.mark.asyncio
async def test_cache_correct_keyed_by_repo_root_and_repo_id(tmp_path: Path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    compute = AsyncMock(side_effect=[_response("impl/repo-a"), _response("impl/repo-b")])

    with patch.object(svc, "_compute_worktree_list_response", new=compute):
        first = await svc.get_all_worktrees(repo_root=repo_a, use_cache=True, cache_repo_id=5)
        second = await svc.get_all_worktrees(repo_root=repo_b, use_cache=True, cache_repo_id=5)

    assert compute.await_count == 2
    assert first.worktrees[0].branch == "impl/repo-a"
    assert second.worktrees[0].branch == "impl/repo-b"


@pytest.mark.asyncio
async def test_cache_performance_same_key_concurrent_requests_single_compute(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    calls = 0

    async def fake_compute(*, repo_root: Path):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return _response("impl/concurrent")

    with patch.object(svc, "_compute_worktree_list_response", side_effect=fake_compute):
        results = await asyncio.gather(*[
            svc.get_all_worktrees(repo_root=repo_root, use_cache=True, cache_repo_id=3)
            for _ in range(10)
        ])

    assert calls == 1
    assert all(result.worktrees[0].branch == "impl/concurrent" for result in results)


@pytest.mark.asyncio
async def test_cache_correct_different_keys_do_not_block_each_other(tmp_path: Path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()

    async def fake_compute(*, repo_root: Path):
        await asyncio.sleep(0.1)
        return _response(f"impl/{repo_root.name}")

    started = time.perf_counter()
    with patch.object(svc, "_compute_worktree_list_response", side_effect=fake_compute):
        first, second = await asyncio.gather(
            svc.get_all_worktrees(repo_root=repo_a, use_cache=True, cache_repo_id=1),
            svc.get_all_worktrees(repo_root=repo_b, use_cache=True, cache_repo_id=1),
        )
    elapsed = time.perf_counter() - started

    assert first.worktrees[0].branch == "impl/repo-a"
    assert second.worktrees[0].branch == "impl/repo-b"
    assert elapsed < 0.18
