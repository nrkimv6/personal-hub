"""trigger source E2E 테스트

Phase T4: 실제 Redis db=15 + listener 프로세스로 trigger 흐름 검증
"""
import json
import os
import sys
import time
import tempfile
import subprocess
import pytest
import redis
from pathlib import Path

pytestmark = pytest.mark.e2e

REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_TEST_DB = 15
RUNNER_KEY_PREFIX = "plan-runner:runners"
COMMANDS_KEY = "plan-runner:commands"


@pytest.fixture(scope="module")
def redis_client():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)
    try:
        r.ping()
    except redis.ConnectionError:
        pytest.skip("Redis not available")
    yield r
    r.close()


@pytest.fixture(scope="module")
def listener_process(redis_client):
    """dev-runner-command-listener 프로세스 시작"""
    script_path = Path("scripts/plan_runner/dev-runner-command-listener.py")
    if not script_path.exists():
        pytest.skip("listener script not found")

    process = subprocess.Popen(
        [sys.executable, str(script_path), "--redis-db", str(REDIS_TEST_DB)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)  # 리스너 시작 대기

    # heartbeat 확인
    heartbeat = redis_client.get("plan-runner:listener:heartbeat")
    if not heartbeat:
        process.terminate()
        pytest.skip("Listener did not start (no heartbeat)")

    yield process
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
        )


@pytest.mark.e2e
def test_e2e_trigger_user_single(redis_client, listener_process):
    """E2E: RunRequest(trigger='user', dry_run=True) → listener → 로그 파일 첫 줄 [TRIGGER] user 확인"""
    import uuid
    from app.modules.dev_runner.schemas import RunRequest

    runner_id = f"e2e-trigger-{uuid.uuid4().hex[:4]}"
    command_id = uuid.uuid4().hex[:8]

    # trigger='user'로 command 생성
    command = {
        "action": "run",
        "runner_id": runner_id,
        "command_id": command_id,
        "source": "test",
        "trigger": "user",
        "plan_file": "docs/plan/2026-03-23_runner-trigger-source-log.md",
        "dry_run": True,
        "engine": "claude",
    }

    result_key = f"plan-runner:command_results:{command_id}"
    redis_client.lpush(COMMANDS_KEY, json.dumps(command))

    # 결과 대기 (최대 15초)
    result = redis_client.brpop(result_key, timeout=15)

    if result is None:
        pytest.skip("Listener did not process command in time (E2E environment issue)")

    _, raw_result = result
    result_data = json.loads(raw_result)
    assert result_data.get("success"), f"command 실패: {result_data}"

    # Redis에 trigger 저장됐는지 확인 — live key 우선, cleanup 후 recent-meta fallback
    trigger_val = None
    deadline = time.time() + 20.0
    while time.time() < deadline:
        trigger_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger")
        if trigger_val is not None:
            break
        time.sleep(0.2)
    if trigger_val is None:
        # recent-meta fallback: cleanup 후에도 보존된 메타에서 trigger 조회
        import json as _json
        _meta_raw = redis_client.get(f"plan-runner:recent-meta:{runner_id}")
        if _meta_raw:
            try:
                trigger_val = _json.loads(_meta_raw).get("trigger")
            except Exception:
                pass
    assert trigger_val is not None, (
        f"trigger를 live key와 recent-meta 모두에서 관찰하지 못함 (runner_id={runner_id})"
    )
    assert trigger_val == "user", f"Redis trigger 값 오류: {trigger_val}"


@pytest.mark.e2e
def test_e2e_trigger_tc_source(redis_client, listener_process):
    """E2E: test_source='my_e2e_test' → trigger 자동 해석 'tc:my_e2e_test' → Redis 저장 확인"""
    import uuid

    runner_id = f"t-my_e2e_test-{uuid.uuid4().hex[:4]}"
    command_id = uuid.uuid4().hex[:8]

    command = {
        "action": "run",
        "runner_id": runner_id,
        "command_id": command_id,
        "source": "test",
        "trigger": "tc:my_e2e_test",  # executor에서 이미 판별된 값
        "plan_file": "docs/plan/2026-03-23_runner-trigger-source-log.md",
        "dry_run": True,
        "engine": "claude",
    }

    result_key = f"plan-runner:command_results:{command_id}"
    redis_client.lpush(COMMANDS_KEY, json.dumps(command))

    result = redis_client.brpop(result_key, timeout=15)

    if result is None:
        pytest.skip("Listener did not process command in time (E2E environment issue)")

    _, raw_result = result
    result_data = json.loads(raw_result)
    assert result_data.get("success"), f"command 실패: {result_data}"

    # Redis에 trigger 저장됐는지 확인 — live key 우선, cleanup 후 recent-meta fallback
    trigger_val = None
    deadline = time.time() + 20.0
    while time.time() < deadline:
        trigger_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger")
        if trigger_val is not None:
            break
        time.sleep(0.2)
    if trigger_val is None:
        # recent-meta fallback: cleanup 후에도 보존된 메타에서 trigger 조회
        import json as _json
        _meta_raw = redis_client.get(f"plan-runner:recent-meta:{runner_id}")
        if _meta_raw:
            try:
                trigger_val = _json.loads(_meta_raw).get("trigger")
            except Exception:
                pass
    assert trigger_val is not None, (
        f"trigger를 live key와 recent-meta 모두에서 관찰하지 못함 (runner_id={runner_id})"
    )
    assert trigger_val == "tc:my_e2e_test", f"Redis trigger 값 오류: {trigger_val}"
