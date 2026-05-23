from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_execution_claim import PlanExecutionClaim
from app.models.plan_record import PlanEvent, PlanRecord
from app.modules.dev_runner.services.plan_execution_claim_service import (
    ClaimConflictError,
    activate_claim,
    claim_plan,
    release_claim,
)
from tests.dev_runner.dummy_plan_lifecycle_helpers import (
    ACTIVE_RUNNERS_KEY,
    RUNNER_KEY_PREFIX,
    MergePhaseBarrier,
    add_plan_runner_scripts_to_path,
    init_multi_runner_lifecycle_repo,
)


SCRIPTS_DIR = add_plan_runner_scripts_to_path()
from merge_queue import acquire_merge_turn, get_merge_queue, get_queue_key, release_merge_turn, _get_repo_id  # noqa: E402
from _dr_process_utils import _cleanup_process_state  # noqa: E402


@pytest.fixture
def claim_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanEvent.__table__.create(bind=engine, checkfirst=True)
    PlanExecutionClaim.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()
    try:
        with patch("app.modules.dev_runner.services.plan_execution_claim_service._write_header"), patch(
            "app.modules.dev_runner.services.plan_execution_claim_service._clear_header"
        ):
            yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def redis_db15():
    client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    patterns = [
        "plan-runner:merge-queue:*",
        "plan-runner:merge-turn:*",
        "plan-runner:runners:t-f-*",
        "plan-runner:active_runners",
        "plan-runner:recent_runners",
        "plan-runner:recent-meta:t-f-*",
    ]

    def cleanup() -> None:
        keys: list[str] = []
        for pattern in patterns:
            keys.extend(list(client.scan_iter(pattern, count=200)))
        if keys:
            client.delete(*keys)

    cleanup()
    try:
        yield client
    finally:
        cleanup()
        client.close()
        client.connection_pool.disconnect()


def _seed_cleanup_runner(redis_client, ctx, *, merge_status: str = "pre_merge") -> None:
    prefix = f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}"
    redis_client.sadd(ACTIVE_RUNNERS_KEY, ctx.runner_id)
    values = {
        "status": "running",
        "pid": "-1",
        "plan_file": str(ctx.original_plan_path),
        "branch": ctx.runner_branch,
        "worktree_path": str(ctx.runner_worktree),
        "test_source": "multi_runner_crash",
        "test_repo_root": str(ctx.repo_root),
        "trigger": "tc:multi_runner_crash",
        "merge_status": merge_status,
    }
    for suffix, value in values.items():
        redis_client.set(f"{prefix}:{suffix}", value)


def test_claim_conflict_blocks_duplicate_runner_and_allows_retry_after_release(tmp_path, claim_db):
    multi = init_multi_runner_lifecycle_repo(tmp_path, runner_ids=("t-f-claim-a",))
    ctx = multi.runner_contexts[0]

    first = claim_plan(claim_db, str(ctx.original_plan_path), runner_id=ctx.runner_id, write_header=False)
    activate_claim(
        claim_db,
        first.claim_id,
        runner_id=ctx.runner_id,
        pid=1234,
        branch=ctx.runner_branch,
        worktree_path=str(ctx.runner_worktree),
    )

    with pytest.raises(ClaimConflictError) as exc_info:
        claim_plan(claim_db, str(ctx.original_plan_path), runner_id="t-f-claim-b", write_header=False)

    assert exc_info.value.existing_claim.runner_id == ctx.runner_id
    worktrees = _git_output(ctx.repo_root, "worktree", "list", "--porcelain")
    assert str(ctx.runner_worktree).replace("\\", "/") in worktrees.replace("\\", "/")
    assert "t-f-claim-b" not in worktrees

    release_claim(claim_db, first.claim_id)
    retry = claim_plan(claim_db, str(ctx.original_plan_path), runner_id="t-f-claim-b", write_header=False)
    assert retry.runner_id == "t-f-claim-b"


def test_merge_queue_serializes_two_runner_merge_turns(tmp_path, redis_db15):
    multi = init_multi_runner_lifecycle_repo(tmp_path, runner_ids=("t-f-queue-a", "t-f-queue-b"))
    repo_id = _get_repo_id(multi.repo_root)
    barrier = MergePhaseBarrier(1)
    results: dict[str, bool] = {}
    b_waiting = threading.Event()

    assert acquire_merge_turn(redis_db15, "t-f-queue-a", repo_id=repo_id, timeout=5, queue_ttl=60)
    barrier.arrive("t-f-queue-a", "merge", timeout=5)

    def acquire_b() -> None:
        client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        try:
            b_waiting.set()
            barrier.arrive("t-f-queue-b", "merge", timeout=5)
            results["b"] = acquire_merge_turn(client, "t-f-queue-b", repo_id=repo_id, timeout=5, queue_ttl=60)
        finally:
            client.close()
            client.connection_pool.disconnect()

    thread = threading.Thread(target=acquire_b, daemon=True)
    thread.start()
    assert b_waiting.wait(timeout=2)
    time.sleep(0.2)

    assert get_merge_queue(redis_db15, repo_id=repo_id) == ["t-f-queue-a", "t-f-queue-b"]
    assert "b" not in results

    assert release_merge_turn(redis_db15, "t-f-queue-a", repo_id=repo_id)
    thread.join(timeout=5)

    assert results["b"] is True
    assert get_merge_queue(redis_db15, repo_id=repo_id) == ["t-f-queue-b"]
    assert release_merge_turn(redis_db15, "t-f-queue-b", repo_id=repo_id)
    assert get_merge_queue(redis_db15, repo_id=repo_id) == []
    assert barrier.phases_for("t-f-queue-a") == ["merge:arrive", "merge:release"]
    assert barrier.phases_for("t-f-queue-b") == ["merge:arrive", "merge:release"]


def test_crash_before_merge_cleanup_removes_test_runner_worktree_and_retry_is_claimable(
    tmp_path, redis_db15, claim_db, monkeypatch
):
    monkeypatch.setenv("DEV_RUNNER_ALLOW_TEST_REPO_ROOT", "1")
    multi = init_multi_runner_lifecycle_repo(tmp_path, runner_ids=("t-f-crash-before",))
    ctx = multi.runner_contexts[0]
    claim = claim_plan(claim_db, str(ctx.original_plan_path), runner_id=ctx.runner_id, write_header=False)
    _seed_cleanup_runner(redis_db15, ctx, merge_status="pre_merge")

    _cleanup_process_state(ctx.runner_id, redis_db15, reason="process_cleanup")
    release_claim(claim_db, claim.claim_id)

    assert not ctx.runner_worktree.exists()
    assert ctx.runner_branch not in _git_output(ctx.repo_root, "branch", "--list", ctx.runner_branch)
    retry = claim_plan(claim_db, str(ctx.original_plan_path), runner_id="t-f-crash-before-retry", write_header=False)
    assert retry.runner_id == "t-f-crash-before-retry"


def test_crash_during_merge_releases_test_repo_scoped_queue_and_leaves_no_merge_head(tmp_path, redis_db15, monkeypatch):
    monkeypatch.setenv("DEV_RUNNER_ALLOW_TEST_REPO_ROOT", "1")
    multi = init_multi_runner_lifecycle_repo(tmp_path, runner_ids=("t-f-crash-merge", "t-f-crash-next"))
    ctx = multi.runner_contexts[0]
    repo_id = _get_repo_id(ctx.repo_root)
    assert acquire_merge_turn(redis_db15, ctx.runner_id, repo_id=repo_id, timeout=5, queue_ttl=60)
    redis_db15.rpush(get_queue_key(repo_id), "t-f-crash-next")
    _seed_cleanup_runner(redis_db15, ctx, merge_status="merging")

    _cleanup_process_state(ctx.runner_id, redis_db15, reason="process_cleanup")

    assert ctx.runner_id not in get_merge_queue(redis_db15, repo_id=repo_id)
    assert get_merge_queue(redis_db15, repo_id=repo_id) == ["t-f-crash-next"]
    assert not (ctx.repo_root / ".git" / "MERGE_HEAD").exists()
    assert not ctx.runner_worktree.exists()


def test_crash_after_done_before_cleanup_removes_residual_worktree(tmp_path, redis_db15, monkeypatch):
    monkeypatch.setenv("DEV_RUNNER_ALLOW_TEST_REPO_ROOT", "1")
    multi = init_multi_runner_lifecycle_repo(tmp_path, runner_ids=("t-f-crash-done",))
    ctx = multi.runner_contexts[0]
    _seed_cleanup_runner(redis_db15, ctx, merge_status="merged")
    ctx.archive_plan_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.archive_plan_path.write_text(
        "# archived\n\n> 상태: 구현완료\n> 완료일: 2026-05-23\n> 진행률: 1/1 (100%)\n\n- [x] done\n",
        encoding="utf-8",
    )
    ctx.original_plan_path.unlink()

    _cleanup_process_state(ctx.runner_id, redis_db15, reason="heartbeat_dead_process")

    assert not ctx.runner_worktree.exists()
    assert ctx.runner_branch not in _git_output(ctx.repo_root, "branch", "--list", ctx.runner_branch)


def _git_output(repo: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout
