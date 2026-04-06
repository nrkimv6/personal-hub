"""T5 HTTP: dev-runner 재실행 시 기존 워커 attach HTTP 응답 검증.

TestClient(app)를 통해 실제 HTTP endpoint를 호출하여 attach 응답을 검증한다.
listener_process fixture의 PID를 살아있는 PID로 활용.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient

from app.main import app

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from _dr_constants import RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY

from tests.dev_runner.conftest_e2e import (
    isolated_redis,
    listener_process,
    REDIS_TEST_DB,
)

BASE_URL = "/api/v1/dev-runner"
RUNNER_KEY = RUNNER_KEY_PREFIX


def _seed_running_runner(r: redis_lib.Redis, runner_id: str, plan_file: str, pid: int):
    """Redis에 running 상태 runner 직접 등록"""
    r.set(f"{RUNNER_KEY}:{runner_id}:status", "running")
    r.set(f"{RUNNER_KEY}:{runner_id}:plan_file", plan_file)
    r.set(f"{RUNNER_KEY}:{runner_id}:pid", str(pid))
    r.set(f"{RUNNER_KEY}:{runner_id}:engine", "claude")
    r.set(f"{RUNNER_KEY}:{runner_id}:start_time", "2026-04-06T17:00:00")
    r.set(f"{RUNNER_KEY}:{runner_id}:execution_count", "2")
    r.sadd(ACTIVE_RUNNERS_KEY, runner_id)


@pytest.fixture(scope="class")
def http_client_for_orphan():
    """attach 테스트 전용 TestClient (이벤트 루프 유지)"""
    with TestClient(app) as client:
        yield client


@pytest.mark.http
class TestRerunOrphanAttachHTTP:
    """HTTP 통합: POST /run attach 응답 검증"""

    def test_run_endpoint_attached_response(
        self, http_client_for_orphan, isolated_redis, listener_process
    ):
        """attach: 동일 plan 실행 중 POST /run → 200 + attached=True"""
        # listener_process.pid를 살아있는 PID로 활용
        live_pid = listener_process.pid
        existing_runner_id = f"http-existing-{uuid.uuid4().hex[:8]}"
        plan_file = "tests/dev_runner/fixtures/test_minimal_plan.md"

        # Redis에 running 상태 등록
        _seed_running_runner(isolated_redis, existing_runner_id, plan_file, live_pid)

        # POST /run (같은 plan_file)
        resp = http_client_for_orphan.post(
            f"{BASE_URL}/run",
            json={
                "plan_file": plan_file,
                "max_cycles": 1,
                "test_source": "tc:rerun-orphan-http",
            },
        )
        assert resp.status_code == 200, f"HTTP 200 기대: {resp.status_code} {resp.text}"

        body = resp.json()
        assert body.get("attached") is True, f"attached=True 기대: {body}"
        assert body.get("runner_id") == existing_runner_id, (
            f"기존 runner_id 기대: {existing_runner_id}, 실제: {body.get('runner_id')}"
        )
        assert body.get("running") is True, f"running=True 기대: {body}"

    def test_run_endpoint_normal_after_stop(
        self, http_client_for_orphan, isolated_redis, listener_process
    ):
        """신규: stop 후 재실행 → attached=False + 새 runner_id"""
        plan_file = "tests/dev_runner/fixtures/test_minimal_plan_b.md"
        stopped_id = f"http-stopped-{uuid.uuid4().hex[:8]}"

        # stopped 상태 (ACTIVE_RUNNERS에 없음)
        isolated_redis.set(f"{RUNNER_KEY}:{stopped_id}:status", "stopped")
        isolated_redis.set(f"{RUNNER_KEY}:{stopped_id}:plan_file", plan_file)
        # ACTIVE_RUNNERS에 추가 안 함

        resp = http_client_for_orphan.post(
            f"{BASE_URL}/run",
            json={
                "plan_file": plan_file,
                "max_cycles": 1,
                "test_source": "tc:rerun-orphan-http-stop",
            },
        )
        assert resp.status_code == 200, f"HTTP 200 기대: {resp.status_code} {resp.text}"

        body = resp.json()
        assert body.get("attached") is not True, f"attached=False 기대: {body}"
        assert body.get("runner_id") != stopped_id, f"새 runner_id 기대: {body}"
