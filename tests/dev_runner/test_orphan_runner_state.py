from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import fakeredis
import fakeredis.aioredis
import pytest

from app.modules.dev_runner.services.executor_service import ExecutorService
from app.modules.dev_runner.services.redis_connection import RUNNER_KEY_PREFIX


@pytest.fixture
def executor(monkeypatch):
    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")
    service = ExecutorService()
    service.redis_client = fakeredis.FakeRedis(decode_responses=True)
    service.async_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return service


@pytest.mark.asyncio
async def test_get_all_runners_returns_orphan_alive_from_heartbeat_and_log(executor, tmp_path):
    runner_id = "abc12345"
    log_file = tmp_path / f"plan-runner-stream-{runner_id}-20260505_230000.log"
    log_file.write_text(
        "[TRIGGER] user | plan=docs/plan/orphan-plan.md\n"
        "[RUN_META] started_at=2026-05-05T23:00:00 | execution_count=3 | plan_key=docs/plan/orphan-plan.md\n"
        "[20:00:00] [INFO] still running\n",
        encoding="utf-8",
    )
    await executor.async_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat", "1")

    with (
        patch("app.database.SessionLocal") as session_local,
        patch(
            "app.modules.dev_runner.services.executor_service.LogFileResolver.find_filesystem_log",
            return_value=log_file,
        ),
    ):
        db = MagicMock()
        session_local.return_value = db
        db.execute.return_value.rowcount = 0
        runners = await executor.get_all_runners()

    orphan = next(r for r in runners if r.runner_id == runner_id)
    assert orphan.visible is True
    assert orphan.orphan_alive is True
    assert orphan.redis_missing is True
    assert orphan.log_file_found is True
    assert orphan.trigger == "user"
    assert orphan.plan_file == "docs/plan/orphan-plan.md"
    assert orphan.display_plan_name == "orphan-plan.md"
    assert orphan.execution_count == 3
    assert orphan.start_time == datetime.fromisoformat("2026-05-05T23:00:00")


@pytest.mark.asyncio
async def test_get_all_runners_excludes_log_only_non_user_orphan(executor, tmp_path):
    runner_id = "def67890"
    log_file = tmp_path / f"plan-runner-stream-{runner_id}-20260505_230000.log"
    log_file.write_text(
        "[TRIGGER] scheduler:nightly | plan=docs/plan/hidden.md\n"
        "[20:00:00] [INFO] hidden log\n",
        encoding="utf-8",
    )
    await executor.async_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat", "1")

    with (
        patch("app.database.SessionLocal") as session_local,
        patch(
            "app.modules.dev_runner.services.executor_service.LogFileResolver.find_filesystem_log",
            return_value=log_file,
        ),
    ):
        db = MagicMock()
        session_local.return_value = db
        db.execute.return_value.rowcount = 0
        runners = await executor.get_all_runners()

    hidden = next(r for r in runners if r.runner_id == runner_id)
    assert hidden.visible is False
    assert hidden.orphan_alive is True
    assert hidden.trigger == "scheduler:nightly"
