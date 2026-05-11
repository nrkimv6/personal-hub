from pathlib import Path

import fakeredis
import pytest
from fastapi import HTTPException

from app.modules.dev_runner.services import executor_service as executor_module
from app.modules.dev_runner.services.executor_service import (
    ACTIVE_RUNNERS_KEY,
    DISMISSED_RUNNERS_KEY,
    RUNNER_KEY_PREFIX,
    ExecutorService,
)
from app.modules.dev_runner.schemas import ReattachRunnerRequest


def _write_log(log_dir: Path, runner_id: str, plan_file: str = "docs/plan/orphan.md") -> Path:
    log_path = log_dir / f"plan-runner-stream-{runner_id}-20260505_230000.log"
    log_path.write_text(
        f"[TRIGGER] user | plan={plan_file} | engine=claude | fix_engine=claude | runner_id={runner_id}\n"
        f"[RUN_META] started_at=2026-05-05T23:00:00 | execution_count=3 | plan_key={plan_file}\n"
        "hello\n",
        encoding="utf-8",
    )
    return log_path


@pytest.fixture
def orphan_service(tmp_path, monkeypatch):
    server = fakeredis.FakeServer()
    sync_client = fakeredis.FakeRedis(server=server, decode_responses=True)
    async_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    service = ExecutorService()
    service.redis_client = sync_client
    service.async_redis = async_client

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(executor_module.config, "LOG_DIR", log_dir)
    monkeypatch.setattr(executor_module.config, "WTOOLS_BASE_DIR", tmp_path)
    return service, log_dir, async_client


def _parent_process(runner_id: str, plan_file: str = "docs/plan/orphan.md") -> list[dict]:
    return [{
        "pid": 4321,
        "pid_kind": "parent",
        "plan_file": plan_file,
        "engine": "claude",
        "runner_id": runner_id,
        "cmdline": f"python -m plan_runner run --plan-file {plan_file} --engine claude --runner-id {runner_id}",
    }]


@pytest.mark.asyncio
async def test_reattach_runner_right_full_evidence_restores_keys(orphan_service, monkeypatch):
    service, log_dir, redis_client = orphan_service
    runner_id = "abc12345"
    plan_file = "docs/plan/orphan.md"
    log_path = _write_log(log_dir, runner_id, plan_file)
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: _parent_process(runner_id, plan_file))

    response = await service.reattach_runner(runner_id, ReattachRunnerRequest())

    assert response.success is True
    assert response.reattach_mode == "full"
    assert await redis_client.smembers(ACTIVE_RUNNERS_KEY) == {runner_id}
    assert await redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status") == "running"
    assert await redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid") == "4321"
    assert await redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file") == plan_file
    assert await redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path") == str(log_path)
    assert await redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger") == "user"


@pytest.mark.asyncio
async def test_reattach_runner_boundary_already_active_rejected(orphan_service, monkeypatch):
    service, log_dir, redis_client = orphan_service
    runner_id = "abc12345"
    _write_log(log_dir, runner_id)
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: _parent_process(runner_id))
    await redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

    with pytest.raises(HTTPException) as exc:
        await service.reattach_runner(runner_id, ReattachRunnerRequest())

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reattach_runner_boundary_log_only_child_limited_mode(orphan_service, monkeypatch):
    service, log_dir, redis_client = orphan_service
    runner_id = "abc12345"
    plan_file = "docs/plan/orphan.md"
    _write_log(log_dir, runner_id, plan_file)
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: [{
        "pid": 8765,
        "pid_kind": "child_engine",
        "plan_file": plan_file,
        "engine": "claude",
        "runner_id": None,
        "cmdline": f"claude {plan_file}",
    }])

    response = await service.reattach_runner(runner_id, ReattachRunnerRequest())

    assert response.reattach_mode == "log_only_child"
    assert await redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:reattach_mode") == "log_only_child"
    assert await redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat") is None


@pytest.mark.asyncio
async def test_reattach_runner_error_low_confidence_rejected(orphan_service, monkeypatch):
    service, log_dir, _redis_client = orphan_service
    runner_id = "abc12345"
    _write_log(log_dir, runner_id)
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: [])

    with pytest.raises(HTTPException) as exc:
        await service.reattach_runner(runner_id, ReattachRunnerRequest())

    assert exc.value.status_code == 422
    assert "candidate confidence is too low" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_reattach_runner_error_dismissed_runner_rejected(orphan_service, monkeypatch):
    service, log_dir, redis_client = orphan_service
    runner_id = "abc12345"
    _write_log(log_dir, runner_id)
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: _parent_process(runner_id))
    await redis_client.sadd(DISMISSED_RUNNERS_KEY, runner_id)

    with pytest.raises(HTTPException) as exc:
        await service.reattach_runner(runner_id, ReattachRunnerRequest())

    assert exc.value.status_code == 409
