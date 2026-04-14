"""T4 E2E: dev-runner 재실행 시 기존 워커 attach 응답 검증.

실제 Redis(db=15) + Listener 프로세스를 사용하여 attach 동작을 E2E 검증한다.
listener_process fixture의 PID를 살아있는 PID로 활용하여 빠르게 검증.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest
import redis as redis_lib

# scripts 경로
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from _dr_constants import RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RESULTS_KEY, COMMANDS_KEY

from tests.dev_runner.conftest_e2e import (
    isolated_redis_db15,
    listener_process,
    REDIS_TEST_DB,
)

RUNNER_KEY = RUNNER_KEY_PREFIX


def _seed_running_runner(r: redis_lib.Redis, runner_id: str, plan_file: str, pid: int):
    """Redis에 running 상태 runner 직접 등록 (listener_process PID 사용)"""
    r.set(f"{RUNNER_KEY}:{runner_id}:status", "running")
    r.set(f"{RUNNER_KEY}:{runner_id}:plan_file", plan_file)
    r.set(f"{RUNNER_KEY}:{runner_id}:pid", str(pid))
    r.set(f"{RUNNER_KEY}:{runner_id}:engine", "claude")
    r.set(f"{RUNNER_KEY}:{runner_id}:start_time", "2026-04-06T17:00:00")
    r.set(f"{RUNNER_KEY}:{runner_id}:execution_count", "1")
    r.sadd(ACTIVE_RUNNERS_KEY, runner_id)


def _send_run_command(r: redis_lib.Redis, plan_file: str, new_runner_id: str, timeout: int = 10) -> dict:
    """listener에 run command 전송 + 결과 대기"""
    command_id = str(uuid.uuid4())
    result_key = f"{RESULTS_KEY}:{command_id}"
    command = {
        "action": "run",
        "runner_id": new_runner_id,
        "plan_file": plan_file,
        "command_id": command_id,
        "engine": "claude",
        "max_cycles": 1,
        "test_source": "tc:rerun-orphan-e2e",
    }
    r.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))

    deadline = time.time() + timeout
    while time.time() < deadline:
        result = r.rpop(result_key)
        if result:
            return json.loads(result)
        time.sleep(0.1)
    return {}


@pytest.mark.e2e
class TestRerunOrphanAttachE2E:
    """E2E: 기존 워커 실행 중 재실행 → attach 응답"""

    def test_run_api_returns_attached_when_plan_running(self, isolated_redis_db15, listener_process):
        """attach: 동일 plan 실행 중 재실행 → attached=True + 기존 runner_id 반환"""
        # listener_process.pid를 살아있는 PID로 사용 (실제 프로세스)
        live_pid = listener_process.pid
        existing_runner_id = f"e2e-existing-{uuid.uuid4().hex[:8]}"
        plan_file = "tests/dev_runner/fixtures/test_minimal_plan.md"

        # 1. Redis에 running 상태 runner 직접 등록
        _seed_running_runner(isolated_redis_db15, existing_runner_id, plan_file, live_pid)

        # 2. 같은 plan_file로 새 run command 전송
        new_runner_id = f"e2e-new-{uuid.uuid4().hex[:8]}"
        result = _send_run_command(isolated_redis_db15, plan_file, new_runner_id, timeout=15)

        # 3. attached 응답 검증
        assert result.get("success") is True, f"success 기대 True: {result}"
        assert result.get("status") == "attached", f"status 기대 attached: {result}"
        assert result.get("runner_id") == existing_runner_id, (
            f"기존 runner_id 기대: {existing_runner_id}, 실제: {result.get('runner_id')}"
        )

    def test_run_api_creates_new_after_full_stop(self, isolated_redis_db15, listener_process):
        """신규: stop 완료 후 재실행 → attached=False + 새 runner_id"""
        # stop 완료 상태: ACTIVE_RUNNERS에 없음
        stopped_runner_id = f"e2e-stopped-{uuid.uuid4().hex[:8]}"
        plan_file = "tests/dev_runner/fixtures/test_minimal_plan_a.md"

        # stopped 상태는 ACTIVE_RUNNERS에 없음 (stop 후 srem)
        isolated_redis_db15.set(f"{RUNNER_KEY}:{stopped_runner_id}:status", "stopped")
        isolated_redis_db15.set(f"{RUNNER_KEY}:{stopped_runner_id}:plan_file", plan_file)
        # ACTIVE_RUNNERS에 추가하지 않음

        new_runner_id = f"e2e-newrun-{uuid.uuid4().hex[:8]}"
        result = _send_run_command(isolated_redis_db15, plan_file, new_runner_id, timeout=15)

        # accepted 응답 (attached 아님) 또는 background thread 시작
        assert result.get("success") is True, f"success 기대 True: {result}"
        assert result.get("status") != "attached", f"attached여서는 안 됨: {result}"
        # runner_id 중요: 새 runner_id 또는 accepted
        assert result.get("message") == "accepted" or result.get("runner_id") == new_runner_id
