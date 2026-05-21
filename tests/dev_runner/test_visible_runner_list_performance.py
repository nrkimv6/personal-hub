"""Visible runner list performance contract.

These tests use fakeredis and in-memory row objects only. They do not touch the
local Redis/Postgres services or production runner state.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.modules.dev_runner.services import executor_service as executor_module
from app.modules.dev_runner.services import visibility
from app.modules.dev_runner.services.executor_service import ExecutorService


@pytest.mark.asyncio
async def test_default_runner_list_skips_hidden_db_rows_before_expensive_read_model(tmp_path, monkeypatch):
    plans_dir = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
    plans_dir.mkdir(parents=True)
    plan_name = "2026-05-21_visible-runner.md"
    (plans_dir / plan_name).write_text("# visible\n", encoding="utf-8")
    monkeypatch.setattr(visibility, "_project_root", lambda: tmp_path)

    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    visible_row = SimpleNamespace(
        runner_id="db-visible-001",
        status="stopped",
        plan_file=f"docs/plan/{plan_name}",
        started_at=datetime.now(),
        branch="impl/visible",
        worktree_path="D:/work/visible",
        exit_reason="completed",
        merge_requested=False,
        metadata_json={"trigger": "user"},
    )
    hidden_rows = {
        f"db-hidden-{index:03d}": SimpleNamespace(
            runner_id=f"db-hidden-{index:03d}",
            status="stopped",
            plan_file="docs/plan/test.md",
            started_at=datetime.now(),
            branch=None,
            worktree_path=None,
            exit_reason=None,
            merge_requested=False,
            metadata_json={"trigger": "user", "test_source": "pytest"},
        )
        for index in range(75)
    }
    rows = {visible_row.runner_id: visible_row, **hidden_rows}
    monkeypatch.setattr(svc, "_load_db_runner_states", lambda limit=200, visible_only=False: rows)
    monkeypatch.setattr(svc, "_correct_pid_state", AsyncMock(return_value=(False, None)))
    monkeypatch.setattr(svc, "_fix_orphan_workflows", MagicMock(return_value=False))
    filesystem_log = MagicMock(return_value=None)
    monkeypatch.setattr(svc, "_filesystem_log_for_runner", filesystem_log)

    original_build_read_model = executor_module.build_runner_read_model
    read_model_calls = []

    def counted_build_read_model(*args, **kwargs):
        read_model_calls.append(kwargs.get("runner_id"))
        return original_build_read_model(*args, **kwargs)

    monkeypatch.setattr(executor_module, "build_runner_read_model", counted_build_read_model)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.database.SessionLocal", return_value=mock_db):
        runners = await svc.get_all_runners()

    assert [runner.runner_id for runner in runners] == ["db-visible-001"]
    assert all(not runner_id.startswith("db-hidden-") for runner_id in read_model_calls)
    assert read_model_calls.count("db-visible-001") == 2
    assert [args[0][0] for args in filesystem_log.call_args_list] == ["db-visible-001"]
