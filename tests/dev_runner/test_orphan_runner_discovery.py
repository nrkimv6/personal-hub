from pathlib import Path
import os
import time

import fakeredis
import pytest

from app.modules.dev_runner.services import executor_service as executor_module
from app.modules.dev_runner.services import visibility
from app.modules.dev_runner.services.executor_service import ExecutorService


def _write_plan_evidence(log_dir: Path, plan_file: str) -> None:
    plan_path = log_dir.parent / ".worktrees" / "plans" / Path(plan_file.replace("\\", "/"))
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("# orphan evidence\n", encoding="utf-8")


def _write_log(log_dir: Path, runner_id: str, plan_file: str = "docs/plan/2026-05-20_orphan-real.md", *, body: str | None = None) -> Path:
    _write_plan_evidence(log_dir, plan_file)
    log_path = log_dir / f"plan-runner-stream-{runner_id}-20260505_230000.log"
    log_path.write_text(
        body
        if body is not None
        else (
            f"[TRIGGER] user | plan={plan_file} | engine=claude | fix_engine=claude | runner_id={runner_id}\n"
            f"[RUN_META] started_at=2026-05-05T23:00:00 | execution_count=3 | plan_key={plan_file}\n"
            "hello\n"
        ),
        encoding="utf-8",
    )
    return log_path


def _make_old(path: Path, seconds: int = 172800) -> None:
    ts = time.time() - seconds
    os.utime(path, (ts, ts))


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
    monkeypatch.setattr(visibility, "_project_root", lambda: tmp_path)
    return service, log_dir


@pytest.mark.asyncio
async def test_discover_orphan_runners_right_log_and_process_evidence(orphan_service, monkeypatch):
    service, log_dir = orphan_service
    runner_id = "abc12345"
    plan_file = "docs/plan/2026-05-20_orphan-parent.md"
    _write_log(log_dir, runner_id, plan_file)
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: [{
        "pid": 4321,
        "pid_kind": "parent",
        "plan_file": plan_file,
        "engine": "claude",
        "runner_id": None,
        "cmdline": f"python -m plan_runner run --plan-file {plan_file} --engine claude",
    }])

    candidates = await service.discover_orphan_runners()

    assert [c.runner_id for c in candidates] == [runner_id]
    assert candidates[0].confidence == "high"
    assert candidates[0].pid == 4321
    assert candidates[0].pid_kind == "parent"
    assert candidates[0].reattach_mode == "full"


@pytest.mark.asyncio
async def test_discover_orphan_runners_boundary_log_only_no_process(orphan_service, monkeypatch):
    service, log_dir = orphan_service
    _write_log(log_dir, "abc12345")
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: [])

    candidates = await service.discover_orphan_runners()

    assert len(candidates) == 1
    assert candidates[0].pid is None
    assert candidates[0].pid_kind == "none"
    assert candidates[0].confidence == "low"
    assert candidates[0].can_reattach is False


@pytest.mark.asyncio
async def test_discover_orphan_runners_boundary_child_only_claude(orphan_service, monkeypatch):
    service, log_dir = orphan_service
    runner_id = "abc12345"
    plan_file = "docs/plan/2026-05-20_orphan-child.md"
    _write_log(log_dir, runner_id, plan_file)
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: [{
        "pid": 6543,
        "pid_kind": "child_engine",
        "plan_file": plan_file,
        "engine": "claude",
        "runner_id": None,
        "cmdline": f"claude --dangerously-skip-permissions {plan_file}",
    }])

    candidates = await service.discover_orphan_runners()

    assert len(candidates) == 1
    assert candidates[0].pid_kind == "child_engine"
    assert candidates[0].reattach_mode == "log_only_child"
    assert "parent_process_missing" in candidates[0].warnings


@pytest.mark.asyncio
async def test_discover_orphan_runners_boundary_empty_redis_no_live(orphan_service, monkeypatch):
    service, _log_dir = orphan_service
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: [])

    assert await service.discover_orphan_runners() == []


def test_match_process_requires_runner_or_plan_evidence(orphan_service):
    service, _log_dir = orphan_service

    match = service._match_process_for_log_candidate(
        "old-runner",
        {"engine": "codex", "plan": "docs/plan/old.md"},
        [{
            "pid": 9999,
            "pid_kind": "child_engine",
            "engine": "codex",
            "runner_id": None,
            "plan_file": None,
            "cmdline": "codex --some-current-session",
        }],
    )

    assert match is None


@pytest.mark.asyncio
async def test_discover_orphans_filters_old_log_only_user_runners(orphan_service, monkeypatch):
    service, log_dir = orphan_service
    log_path = _write_log(log_dir, "old-user-runner")
    _make_old(log_path)
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: [])

    candidates = await service.discover_orphan_runners()

    assert candidates == []


@pytest.mark.asyncio
async def test_discover_orphans_keeps_recent_high_confidence_parent_runner(orphan_service, monkeypatch):
    service, log_dir = orphan_service
    runner_id = "recent-parent"
    plan_file = "docs/plan/recent-parent.md"
    _write_log(log_dir, runner_id, plan_file)
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: [{
        "pid": 2026,
        "pid_kind": "parent",
        "plan_file": plan_file,
        "engine": "claude",
        "runner_id": runner_id,
        "cmdline": f"python -m plan_runner run --runner-id {runner_id} --plan-file {plan_file} --engine claude",
    }])

    candidates = await service.discover_orphan_runners()

    assert [c.runner_id for c in candidates] == [runner_id]
    assert candidates[0].confidence == "high"
    assert candidates[0].can_reattach is True


@pytest.mark.asyncio
async def test_discover_orphans_filters_test_trigger_candidates(orphan_service, monkeypatch):
    service, log_dir = orphan_service
    runner_id = "tc-pytest-orphan"
    _write_log(
        log_dir,
        runner_id,
        body=(
            f"[TRIGGER] tc:orphan | plan=docs/plan/test.md | engine=claude | runner_id={runner_id}\n"
            "[RUN_META] started_at=2026-05-20T10:00:00 | execution_count=1 | plan_key=docs/plan/test.md\n"
            "test output\n"
        ),
    )
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: [{
        "pid": 3030,
        "pid_kind": "parent",
        "plan_file": "docs/plan/test.md",
        "engine": "claude",
        "runner_id": runner_id,
        "cmdline": f"python -m plan_runner run --runner-id {runner_id} --plan-file docs/plan/test.md",
    }])

    candidates = await service.discover_orphan_runners()

    assert candidates == []


@pytest.mark.asyncio
async def test_discover_orphan_runners_error_corrupt_log_header(orphan_service, monkeypatch):
    service, log_dir = orphan_service
    _write_log(log_dir, "abc12345", body="not a dev-runner header\n")
    monkeypatch.setattr(service, "_list_live_runner_processes", lambda: [])

    assert await service.discover_orphan_runners() == []
