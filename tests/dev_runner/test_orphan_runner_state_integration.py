from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import fakeredis
import fakeredis.aioredis
import pytest

from app.modules.dev_runner.services import executor_service as executor_module
from app.modules.dev_runner.services.executor_service import ExecutorService
from app.modules.dev_runner.services.log_service import LogService
from app.modules.dev_runner.services.redis_connection import RUNNER_KEY_PREFIX


@pytest.mark.asyncio
async def test_orphan_runner_state_and_recent_log_fallback_integration(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")
    runner_id = "abc12345"
    latest_empty = tmp_path / f"plan-runner-stream-{runner_id}-20260505_230000.log"
    previous_stream = tmp_path / f"plan-runner-stream-{runner_id}-20260505_225900.log"
    main_log = tmp_path / f"plan-runner-{runner_id}-20260505_225900.log"
    latest_empty.write_bytes(b"")
    previous_stream.write_text(
        "[TRIGGER] user | plan=docs/plan/integration-plan.md\n"
        "[RUN_META] started_at=2026-05-05T22:59:00 | execution_count=2 | plan_key=docs/plan/integration-plan.md\n"
        "[20:00:00] [INFO] previous stream output\n",
        encoding="utf-8",
    )
    main_log.write_text("[20:00:00] [INFO] main output\n", encoding="utf-8")

    sync_redis = fakeredis.FakeRedis(decode_responses=True)
    async_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await async_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat", "1")

    executor = ExecutorService()
    executor.redis_client = sync_redis
    executor.async_redis = async_redis
    log_service = LogService.__new__(LogService)
    log_service.redis_client = sync_redis
    log_service._legacy_map = {}

    with (
        patch("app.database.SessionLocal") as session_local,
        patch(
            "app.modules.dev_runner.services.log_file_resolver.LogFileResolver.get_log_dir",
            return_value=tmp_path,
        ),
    ):
        db = MagicMock()
        session_local.return_value = db
        db.execute.return_value.rowcount = 0

        runners = await executor.get_all_runners()
        recent = log_service.tail_log_file(runner_id, n_lines=100)

    orphan = next(r for r in runners if r.runner_id == runner_id)
    assert orphan.orphan_alive is True
    assert orphan.visible is True
    assert orphan.plan_file == "docs/plan/integration-plan.md"
    assert recent.lines
    assert "previous stream output" in "\n".join(recent.lines)
    assert "START" not in "\n".join(recent.lines)


def _write_orphan_log(log_dir, runner_id, *, trigger="user", plan_file=None):
    plan_file = plan_file or f"docs/plan/{runner_id}.md"
    path = log_dir / f"plan-runner-stream-{runner_id}-20260501_120000.log"
    path.write_text(
        f"[TRIGGER] {trigger} | plan={plan_file} | engine=codex | runner_id={runner_id}\n"
        f"[RUN_META] started_at=2026-05-01T12:00:00 | execution_count=1 | plan_key={plan_file}\n"
        "old output\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_orphan_discovery_does_not_resurrect_bulk_old_logs_with_engine_process(monkeypatch, tmp_path):
    sync_redis = fakeredis.FakeRedis(decode_responses=True)
    async_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    executor = ExecutorService()
    executor.redis_client = sync_redis
    executor.async_redis = async_redis

    old_ts = time.time() - (executor_module.ORPHAN_LOG_MAX_AGE_SECONDS + 3600)
    for idx in range(250):
        path = _write_orphan_log(tmp_path, f"old-{idx:03d}")
        os.utime(path, (old_ts, old_ts))

    monkeypatch.setattr(executor_module.config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(executor_module.config, "WTOOLS_BASE_DIR", tmp_path)
    monkeypatch.setattr(executor, "_list_live_runner_processes", lambda: [{
        "pid": 4444,
        "pid_kind": "child_engine",
        "plan_file": None,
        "engine": "codex",
        "runner_id": None,
        "cmdline": "codex --current-workspace-session",
    }])

    candidates = await executor.discover_orphan_runners()

    assert candidates == []


@pytest.mark.asyncio
async def test_orphan_discovery_keeps_dismissed_runner_suppressed(monkeypatch, tmp_path):
    sync_redis = fakeredis.FakeRedis(decode_responses=True)
    async_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    executor = ExecutorService()
    executor.redis_client = sync_redis
    executor.async_redis = async_redis
    runner_id = "dismissed-runner"
    plan_file = "docs/plan/dismissed.md"
    _write_orphan_log(tmp_path, runner_id, plan_file=plan_file)
    await async_redis.sadd("plan-runner:dismissed_runners", runner_id)

    monkeypatch.setattr(executor_module.config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(executor_module.config, "WTOOLS_BASE_DIR", tmp_path)
    monkeypatch.setattr(executor, "_list_live_runner_processes", lambda: [{
        "pid": 5555,
        "pid_kind": "parent",
        "plan_file": plan_file,
        "engine": "codex",
        "runner_id": runner_id,
        "cmdline": f"python -m plan_runner run --runner-id {runner_id} --plan-file {plan_file}",
    }])

    candidates = await executor.discover_orphan_runners()

    assert candidates == []
