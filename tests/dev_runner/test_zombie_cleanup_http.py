"""T5 HTTP: zombie cleanup 이후 API 상태 반영 검증."""

from __future__ import annotations

import importlib.util
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.modules.dev_runner.routes.runner import router as runner_router
from app.modules.dev_runner.routes.workflows import router as workflows_router
from app.modules.dev_runner.services.executor_service import executor_service
from tests.dev_runner._path_helpers import get_listener_script_path, skip_if_missing

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"

_listener_mod = None


def _runner_key(runner_id: str, suffix: str) -> str:
    return f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"


def _load_listener_module():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    script_path = get_listener_script_path()
    skip_if_missing(script_path, "Listener script")
    spec = importlib.util.spec_from_file_location("dev_runner_command_listener_zombie_http", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _listener_mod = mod
    return mod


def _seed_running_runner(redis_client, runner_id: str, pid: int) -> None:
    old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
    redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)
    redis_client.set(_runner_key(runner_id, "status"), "running")
    redis_client.set(_runner_key(runner_id, "pid"), str(pid))
    redis_client.set(_runner_key(runner_id, "start_time"), old_start)
    redis_client.set(_runner_key(runner_id, "merge_status"), "pending_merge")


@pytest.fixture(autouse=True)
def reset_listener_state():
    listener_mod = _load_listener_module()
    state_mod = sys.modules["_dr_state"]
    state_mod.set_wf_manager(None)
    state_mod.get_running_processes().clear()
    state_mod.get_running_log_files().clear()
    state_mod.get_stream_threads().clear()
    state_mod.get_cleanup_done().clear()
    state_mod.get_dead_process_first_seen().clear()
    state_mod.get_zombie_first_seen().clear()
    yield
    state_mod.set_wf_manager(None)
    state_mod.get_running_processes().clear()
    state_mod.get_running_log_files().clear()
    state_mod.get_stream_threads().clear()
    state_mod.get_cleanup_done().clear()
    state_mod.get_dead_process_first_seen().clear()
    state_mod.get_zombie_first_seen().clear()


@pytest.fixture
def client(test_db_engine):
    app = FastAPI()
    app.include_router(runner_router, prefix=BASE_URL)
    app.include_router(workflows_router, prefix=BASE_URL)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def fake_services(test_db_engine):
    server = fakeredis.FakeServer()
    fake_sync = fakeredis.FakeRedis(server=server, decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)

    with patch.object(executor_service, "redis_client", fake_sync), \
         patch.object(executor_service, "async_redis", fake_async), \
         patch("app.database.SessionLocal", SessionLocal), \
         patch("app.core.database.SessionLocal", SessionLocal):
        yield {"sync": fake_sync, "async": fake_async}


def test_zombie_cleanup_reflected_in_runner_status_api(client, fake_services):
    """zombie cleanup 후 GET /runners 응답에 stopped + zombie 사유가 반영된다."""
    listener_mod = _load_listener_module()
    state_mod = sys.modules["_dr_state"]
    fake_sync = fake_services["sync"]

    runner_id = f"http-zombie-{uuid.uuid4().hex[:8]}"
    proc = MagicMock()
    proc.pid = 45678

    _seed_running_runner(fake_sync, runner_id, proc.pid)
    state_mod.get_running_processes()[runner_id] = proc
    state_mod.get_zombie_first_seen()[runner_id] = time.time() - listener_mod.ZOMBIE_GRACE_SECONDS - 1

    cleaned = listener_mod._handle_zombie_heartbeat(runner_id, proc, fake_sync, wf_manager=None)
    assert cleaned is True

    resp = client.get(f"{BASE_URL}/runners")
    assert resp.status_code == 200
    payload = resp.json()
    target = next((item for item in payload if item.get("runner_id") == runner_id), None)
    assert target is not None, f"runner {runner_id}가 /runners 응답에 없음"
    assert target["running"] is False
    assert "zombie" in (target.get("exit_reason") or "")


def test_zombie_cleanup_workflow_status_api(client, fake_services, test_db_engine):
    """zombie cleanup 후 workflow API가 failed + zombie 에러 메시지를 반환한다."""
    listener_mod = _load_listener_module()
    state_mod = sys.modules["_dr_state"]
    fake_sync = fake_services["sync"]

    from workflow_manager import WorkflowManager

    db_path = Path(str(test_db_engine.url.database))
    wf_manager = WorkflowManager(db_path)

    runner_id = f"wf-zombie-{uuid.uuid4().hex[:8]}"
    proc = MagicMock()
    proc.pid = 56789

    workflow_id = wf_manager.create(
        slug=f"wf-zombie-{uuid.uuid4().hex[:6]}",
        plan_file="docs/plan/2026-04-03_fix-zombie-runner-heartbeat-detection_todo-2.md",
    )
    wf_manager.update_status(workflow_id, "running", runner_id=runner_id, engine="claude")
    state_mod.set_wf_manager(wf_manager)

    _seed_running_runner(fake_sync, runner_id, proc.pid)
    state_mod.get_running_processes()[runner_id] = proc
    state_mod.get_zombie_first_seen()[runner_id] = time.time() - listener_mod.ZOMBIE_GRACE_SECONDS - 1

    cleaned = listener_mod._handle_zombie_heartbeat(runner_id, proc, fake_sync, wf_manager=wf_manager)
    assert cleaned is True

    resp = client.get(f"{BASE_URL}/workflows/{workflow_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert "zombie: subprocess heartbeat timeout" in (data.get("error_message") or "")
