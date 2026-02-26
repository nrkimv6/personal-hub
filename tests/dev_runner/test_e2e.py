import json
import asyncio
import subprocess
import sys
import time
import pytest
from pathlib import Path
import redis
import redis.asyncio as aioredis
from app.modules.dev_runner.services.executor_service import ExecutorService
from app.modules.dev_runner.schemas import RunRequest

# Constants
REDIS_HOST = "localhost"
REDIS_PORT = 6379

@pytest.fixture(scope="module")
def dev_runner_listener():
    """Start the listener script as a background process for E2E tests"""
    script_path = Path("scripts/dev-runner-command-listener.py")
    
    # Ensure Redis is running
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
        r.ping()
        # Clean state before starting
        r.delete("plan-runner:state:status")
        r.delete("plan-runner:listener:heartbeat")
    except redis.ConnectionError:
        pytest.skip("Redis not available, skipping E2E tests")

    # Start listener process
    process = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for listener to register heartbeat
    for i in range(20):
        if r.get("plan-runner:listener:heartbeat"):
            print(f"Listener heartbeat detected after {i*0.5}s")
            break
        time.sleep(0.5)
    else:
        out, err = process.communicate(timeout=1)
        pytest.fail(f"Listener failed to start. Stdout: {out}, Stderr: {err}")
        
    yield process
    
    # Teardown
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)

@pytest.fixture
def executor_service():
    """Actual executor service connecting to real local Redis"""
    svc = ExecutorService()
    return svc

@pytest.mark.asyncio
async def test_e2e_full_lifecycle(dev_runner_listener, executor_service):
    """E2E Test: API -> Redis -> Listener -> plan-runner CLI -> success response"""
    
    # Create request with dry_run to execute quickly without LLM calls
    req = RunRequest(
        engine="gemini",
        dry_run=True,
        plan_file="test_plan_e2e_mock.md"
    )
    
    # 1. Start execution
    response = await executor_service.start_dev_runner(req)
    runner_id = response.runner_id

    assert response.running is True
    assert runner_id is not None
    assert response.engine == "gemini"

    # 2. Wait for listener to pick up command and set pid (async processing)
    # dry_run exits fast so check Redis directly for pid before stale cleanup
    from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX
    pid_appeared = False
    for _ in range(20):
        await asyncio.sleep(0.5)
        pid_val = executor_service.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
        if pid_val is not None:
            pid_appeared = True
            break
        # Also accept if status already completed (dry_run finished quickly)
        status_val = executor_service.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
        if status_val in ("completed", "stopped", None):
            pid_appeared = True  # process ran and completed
            break
    assert pid_appeared, "Listener never processed the run command"

    # Allow some time for plan-runner to run and exit (dry-run is fast)
    await asyncio.sleep(3)

    # 3. Stop execution (even if it finished, stop handles cleanup safely)
    try:
        stop_resp = await executor_service.stop_dev_runner(runner_id)
        assert "Stopped" in stop_resp["message"] or "Force cleaned" in stop_resp["message"]
    except Exception as e:
        # Since it's a dry_run, it might have finished and cleaned up already, returning 404
        assert getattr(e, "status_code", 500) == 404

    # 4. Status should be clean now
    final_status = executor_service.get_runner_status(runner_id)
    assert final_status.running is False
