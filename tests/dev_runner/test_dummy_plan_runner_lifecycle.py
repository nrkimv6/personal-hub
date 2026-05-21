from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.dev_runner.conftest_e2e import copy_fixture_plan_to_tmp
from tests.dev_runner.dummy_plan_lifecycle_helpers import (
    ACTIVE_RUNNERS_KEY,
    COMMANDS_KEY,
    DUMMY_PLAN_FIXTURE,
    DUMMY_PLAN_SENTINEL,
    RECENT_RUNNERS_KEY,
    RUNNER_KEY_PREFIX,
    add_plan_runner_scripts_to_path,
    cleanup_dummy_runner_state,
    init_dummy_temp_repo,
    normalize_path,
    seed_dummy_runner_state,
)


pytestmark = pytest.mark.http
BASE_URL = "/api/v1/dev-runner"


@pytest.fixture(autouse=True)
def _plan_runner_redis_db_guard(monkeypatch):
    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")


@pytest.fixture
def fake_server():
    return fakeredis.FakeServer()


@pytest.fixture
def fake_sync(fake_server):
    return fakeredis.FakeRedis(server=fake_server, decode_responses=True)


@pytest.fixture
def fake_async(fake_server):
    return fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)


@pytest.fixture
def api_client(fake_sync, fake_async):
    from app.modules.dev_runner.routes import router as dev_runner_router
    from app.modules.dev_runner.services.executor_service import executor_service
    from app.modules.dev_runner.services.log_service import log_service

    original_sync = executor_service.redis_client
    original_async = executor_service.async_redis
    original_log_sync = log_service.redis_client
    original_resolver = log_service.resolver
    executor_service.redis_client = fake_sync
    executor_service.async_redis = fake_async
    log_service.redis_client = fake_sync
    log_service.resolver = None

    app = FastAPI()
    app.include_router(dev_runner_router)

    try:
        with TestClient(app) as client:
            yield client, fake_sync, fake_async
    finally:
        executor_service.redis_client = original_sync
        executor_service.async_redis = original_async
        log_service.redis_client = original_log_sync
        log_service.resolver = original_resolver


def _runner_prefix(runner_id: str) -> str:
    return f"{RUNNER_KEY_PREFIX}:{runner_id}"


def test_start_dummy_plan_R_enqueues_command_with_plan_file_and_test_source(api_client, tmp_path):
    client, fake_sync, fake_async = api_client
    fake_sync.set("plan-runner:listener:heartbeat", "alive")
    plan_file = copy_fixture_plan_to_tmp(tmp_path, DUMMY_PLAN_FIXTURE)
    captured_commands: list[dict] = []

    async def capture_enqueue(command):
        captured_commands.append(command)
        command_id = command.get("command_id", "dummycmd")
        return {
            "success": True,
            "status": "accepted",
            "command_id": command_id,
            "result_key": f"plan-runner:results:{command_id}",
            "message": "Command accepted",
        }

    settings = SimpleNamespace(
        max_concurrent_runners=3,
        default_engine="claude",
        default_fix_engine="claude",
    )
    with patch(
        "app.modules.dev_runner.services.executor_service.settings_service.get",
        return_value=settings,
    ), patch(
        "app.modules.dev_runner.services.executor_service.ExecutorService._enqueue_command",
        new=AsyncMock(side_effect=capture_enqueue),
    ), patch(
        "app.modules.dev_runner.services.executor_service.ExecutorService._best_effort_upsert_runner_state"
    ):
        response = client.post(
            f"{BASE_URL}/run",
            json={
                "plan_file": str(plan_file),
                "test_source": "dummy_plan_playwright",
                "engine": "codex",
                "fix_engine": "codex",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["running"] is True
    assert body["runner_id"].startswith("t-dummy_plan_playwri")
    assert body["plan_file"] == str(plan_file)

    assert len(captured_commands) == 1
    command = captured_commands[0]
    assert command["action"] == "run"
    assert command["plan_file"] == str(plan_file)
    assert command["test_source"] == "dummy_plan_playwright"
    assert command["trigger"] == "tc:dummy_plan_playwright"
    assert command["engine"] == "codex"
    assert command["fix_engine"] == "codex"

    runner_id = body["runner_id"]
    artifacts = seed_dummy_runner_state(
        fake_sync,
        runner_id=runner_id,
        plan_file=plan_file,
        tmp_path=tmp_path,
        stream_lines=[f"[INFO] {DUMMY_PLAN_SENTINEL}"],
    )
    response = client.get(f"{BASE_URL}/runners")
    assert response.status_code == 200
    runner = next(item for item in response.json() if item["runner_id"] == runner_id)
    assert runner["plan_file"] == str(plan_file)
    assert normalize_path(runner["display_plan_name"] or runner["plan_file"]).endswith(DUMMY_PLAN_FIXTURE)
    assert runner["running"] is True
    assert runner["visible"] is False
    assert normalize_path(artifacts.stream_log_path).endswith(f"plan-runner-stream-{runner_id}.log")


def test_dummy_plan_log_R_recent_and_full_include_sentinel(api_client, tmp_path):
    client, fake_sync, fake_async = api_client
    runner_id = "t-dummy-log-sentinel"
    plan_file = copy_fixture_plan_to_tmp(tmp_path, DUMMY_PLAN_FIXTURE)
    seed_dummy_runner_state(
        fake_sync,
        runner_id=runner_id,
        plan_file=plan_file,
        tmp_path=tmp_path,
        stream_lines=[
            "[INFO] preparing dummy plan",
            f"[INFO] {DUMMY_PLAN_SENTINEL}",
            "[MERGE] dummy merge log retained",
        ],
    )

    recent = client.get(f"{BASE_URL}/logs/recent", params={"runner_id": runner_id, "lines": 2})
    assert recent.status_code == 200
    assert any(DUMMY_PLAN_SENTINEL in line for line in recent.json()["lines"])

    full = client.get(f"{BASE_URL}/logs/full", params={"runner_id": runner_id, "offset": 1, "limit": 2})
    assert full.status_code == 200
    full_body = full.json()
    assert full_body["offset"] == 1
    assert full_body["total_lines"] == 3
    assert any(DUMMY_PLAN_SENTINEL in line for line in full_body["lines"])

    artifacts = seed_dummy_runner_state(
        fake_sync,
        runner_id=f"{runner_id}-fallback",
        plan_file=plan_file,
        tmp_path=tmp_path,
        stream_lines=[],
    )
    artifacts.stream_log_path.unlink()
    artifacts.log_file_path.unlink()
    fake_sync.rpush(f"plan-runner:logs:list:{artifacts.runner_id}", f"[MERGE] {DUMMY_PLAN_SENTINEL} redis fallback")
    fallback = client.get(f"{BASE_URL}/logs/recent", params={"runner_id": artifacts.runner_id, "lines": 10})
    assert fallback.status_code == 200
    assert fallback.json()["lines"] == [f"[MERGE] {DUMMY_PLAN_SENTINEL} redis fallback"]


def test_dummy_plan_merge_R_temp_repo_marker_reaches_main(api_client, tmp_path, monkeypatch):
    client, fake_sync, fake_async = api_client
    add_plan_runner_scripts_to_path()
    import _dr_merge as dr_merge
    from worktree_manager import WorktreeManager

    runner_id = "t-dummy-merge-main"
    plan_file = copy_fixture_plan_to_tmp(tmp_path, DUMMY_PLAN_FIXTURE)
    repo = init_dummy_temp_repo(tmp_path, runner_id=runner_id)
    seed_dummy_runner_state(
        fake_sync,
        runner_id=runner_id,
        plan_file=plan_file,
        tmp_path=tmp_path,
        stream_lines=[f"[INFO] {DUMMY_PLAN_SENTINEL}"],
        repo=repo,
    )

    result = WorktreeManager.merge_to_main(
        runner_id,
        repo.worktree_base,
        repo.repo_root,
        branch=repo.branch,
        use_runner_identity=True,
    )
    assert result.success is True
    assert (repo.repo_root / repo.marker_relpath).read_text(encoding="utf-8") == repo.marker_text

    fake_sync.set(f"{_runner_prefix(runner_id)}:merge_status", "merged")
    fake_sync.set(f"{_runner_prefix(runner_id)}:merge_message", "dummy temp repo merged")
    dr_merge._pub_and_log(runner_id, f"{DUMMY_PLAN_SENTINEL} merge completed", fake_sync)

    merge_status = client.get(f"{BASE_URL}/merge/{runner_id}")
    assert merge_status.status_code == 200
    assert merge_status.json()["status"] == "merged"
    redis_logs = fake_sync.lrange(f"plan-runner:logs:list:{runner_id}", 0, -1)
    assert any(DUMMY_PLAN_SENTINEL in line for line in redis_logs)
    stream_log = fake_sync.get(f"{_runner_prefix(runner_id)}:stream_log_path")
    assert DUMMY_PLAN_SENTINEL in (tmp_path / "logs" / f"plan-runner-stream-{runner_id}.log").read_text(encoding="utf-8")
    assert normalize_path(stream_log).endswith(f"plan-runner-stream-{runner_id}.log")


def test_dummy_plan_B_teardown_removes_runner_keys_and_worktree(api_client, tmp_path):
    client, fake_sync, fake_async = api_client
    runner_id = "t-dummy-cleanup"
    plan_file = copy_fixture_plan_to_tmp(tmp_path, DUMMY_PLAN_FIXTURE)
    repo = init_dummy_temp_repo(tmp_path, runner_id=runner_id)
    seed_dummy_runner_state(
        fake_sync,
        runner_id=runner_id,
        plan_file=plan_file,
        tmp_path=tmp_path,
        repo=repo,
    )
    assert list(fake_sync.scan_iter(f"{_runner_prefix(runner_id)}:*"))
    assert repo.worktree_path.exists()

    cleanup_dummy_runner_state(fake_sync, runner_id, temp_root=tmp_path)

    assert list(fake_sync.scan_iter(f"{_runner_prefix(runner_id)}:*")) == []
    assert runner_id not in fake_sync.smembers(ACTIVE_RUNNERS_KEY)
    assert runner_id not in fake_sync.zrange(RECENT_RUNNERS_KEY, 0, -1)
    assert not repo.worktree_path.exists()
    branches = subprocess.run(
        ["git", "branch", "--list", repo.branch],
        cwd=str(repo.repo_root),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert branches.stdout.strip() == ""


def test_dummy_plan_E_listener_missing_returns_503_without_artifacts(api_client, tmp_path):
    client, fake_sync, fake_async = api_client
    plan_file = copy_fixture_plan_to_tmp(tmp_path, DUMMY_PLAN_FIXTURE)

    response = client.post(
        f"{BASE_URL}/run",
        json={
            "plan_file": str(plan_file),
            "test_source": "dummy_plan_playwright",
            "engine": "codex",
            "fix_engine": "codex",
        },
    )

    assert response.status_code == 503
    assert "listener" in json.dumps(response.json(), ensure_ascii=False).lower()
    assert fake_sync.llen(COMMANDS_KEY) == 0
    assert fake_sync.scard(ACTIVE_RUNNERS_KEY) == 0
    assert list(fake_sync.scan_iter(f"{RUNNER_KEY_PREFIX}:t-dummy_plan_playwri*")) == []
