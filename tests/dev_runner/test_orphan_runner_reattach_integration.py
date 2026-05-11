from pathlib import Path

import fakeredis
import pytest

from app.modules.dev_runner.services import executor_service as executor_module
from app.modules.dev_runner.services.executor_service import ExecutorService
from app.modules.dev_runner.services.log_file_resolver import LogFileResolver
from app.modules.dev_runner.services.log_service import LogService
from app.modules.dev_runner.schemas import ReattachRunnerRequest


@pytest.fixture
def redis_backed_orphan(tmp_path, monkeypatch):
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
    monkeypatch.setattr(service, "_is_pid_alive", lambda _pid: True)
    return service, sync_client, log_dir


def _write_log(log_dir: Path, runner_id: str, plan_file: str) -> Path:
    log_path = log_dir / f"plan-runner-stream-{runner_id}-20260505_230000.log"
    log_path.write_text(
        f"[TRIGGER] user | plan={plan_file} | engine=claude | fix_engine=claude | runner_id={runner_id}\n"
        f"[RUN_META] started_at=2026-05-05T23:00:00 | execution_count=1 | plan_key={plan_file}\n"
        "line after reattach\n",
        encoding="utf-8",
    )
    return log_path


@pytest.mark.asyncio
async def test_orphan_candidate_reattach_returns_to_active_and_keeps_recent_log(redis_backed_orphan, monkeypatch):
    service, sync_client, log_dir = redis_backed_orphan
    runner_id = "abc12345"
    plan_file = "docs/plan/orphan.md"
    _write_log(log_dir, runner_id, plan_file)
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: [{
        "pid": 4321,
        "pid_kind": "parent",
        "plan_file": plan_file,
        "engine": "claude",
        "runner_id": runner_id,
        "cmdline": f"python -m plan_runner run --plan-file {plan_file} --runner-id {runner_id}",
    }])

    candidates = await service.discover_orphan_runners()
    assert [candidate.runner_id for candidate in candidates] == [runner_id]

    await service.reattach_runner(runner_id, ReattachRunnerRequest())
    runners = await service.get_all_runners()

    assert any(runner.runner_id == runner_id and runner.running for runner in runners)

    log_service = LogService.__new__(LogService)
    log_service.redis_client = sync_client
    log_service.resolver = LogFileResolver(executor_module.config, sync_client)
    log_service._legacy_map = {}
    log_service._get_log_dir = lambda: log_dir
    recent = log_service.tail_log_file(runner_id, n_lines=5)

    assert "line after reattach" in recent.lines
