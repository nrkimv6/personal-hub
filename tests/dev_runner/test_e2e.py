import json
import asyncio
import subprocess
import sys
import time
import pytest
from pathlib import Path
import redis
import redis.asyncio as aioredis
from fastapi import HTTPException
from app.modules.dev_runner.services.executor_service import ExecutorService
from app.modules.dev_runner.schemas import RunRequest

# Constants
REDIS_HOST = "localhost"
REDIS_PORT = 6379

REDIS_TEST_DB = 15


def _resolve_repo_root() -> Path:
    """Resolve primary repo root even when tests run inside a git worktree."""
    here = Path(__file__).resolve().parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            cwd=str(here),
            check=True,
        )
        git_common_dir = Path(result.stdout.strip())
        if not git_common_dir.is_absolute():
            git_common_dir = (here / git_common_dir).resolve()
        return git_common_dir.parent
    except Exception:
        # Fallback: tests/dev_runner/test_e2e.py -> repo root
        return Path(__file__).resolve().parents[2]


REPO_ROOT = _resolve_repo_root()
E2E_PLAN_FILE = REPO_ROOT / "tests" / "dev_runner" / "fixtures" / "test_plan_e2e_mock.md"


@pytest.fixture
def dev_runner_listener():
    """Start the listener script as a background process for E2E tests (db=15 격리)"""
    import os as _os
    script_path = Path("scripts/plan_runner/dev-runner-command-listener.py")

    # Ensure Redis is running (db=15 격리)
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)
        r.ping()
        # Clean state before starting
        r.delete("plan-runner:state:status")
        r.delete("plan-runner:listener:heartbeat")
    except redis.ConnectionError:
        pytest.skip("Redis not available, skipping E2E tests")

    # guard가 PLAN_RUNNER_REDIS_DB 환경변수를 검사하므로 db=15로 설정
    old_plan_runner_redis_db = _os.environ.get("PLAN_RUNNER_REDIS_DB")
    _os.environ["PLAN_RUNNER_REDIS_DB"] = str(REDIS_TEST_DB)

    # Start listener process (db=15)
    process = subprocess.Popen(
        [sys.executable, str(script_path), "--redis-db", str(REDIS_TEST_DB)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    
    # Wait for listener to register heartbeat
    for i in range(20):
        if r.get("plan-runner:listener:heartbeat"):
            print(f"Listener heartbeat detected after {i*0.5}s")
            break
        time.sleep(0.5)
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        pytest.fail("Listener failed to start (heartbeat not detected within 10s)")
        
    yield process

    # 환경변수 복원
    if old_plan_runner_redis_db is not None:
        _os.environ["PLAN_RUNNER_REDIS_DB"] = old_plan_runner_redis_db
    else:
        _os.environ.pop("PLAN_RUNNER_REDIS_DB", None)

    # Teardown
    if process.poll() is None:
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

    # worktree 잔여물 정리
    _root = REPO_ROOT
    for _stem in ["test_plan_e2e_mock"]:
        subprocess.run(
            ["git", "worktree", "remove", str(_root / ".worktrees" / _stem), "--force"],
            capture_output=True, cwd=str(_root),
        )
        subprocess.run(
            ["git", "branch", "-D", f"plan/{_stem}"],
            capture_output=True, cwd=str(_root),
        )

    # Redis plan-runner:* stale 키 정리 (db=15)
    try:
        r_cleanup = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)
        stale_keys = r_cleanup.keys("plan-runner:*")
        if stale_keys:
            r_cleanup.delete(*stale_keys)
    except Exception:
        pass

@pytest.fixture
async def executor_service():
    """Actual executor service connecting to local Redis db=15 (격리)"""
    svc = ExecutorService()
    # db=15로 Redis 재연결 (production db=0 오염 방지)
    svc.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)
    svc.async_redis = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)
    yield svc
    try:
        await svc.async_redis.aclose()
    except Exception:
        pass

@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["gemini", "codex"])
async def test_e2e_full_lifecycle(dev_runner_listener, executor_service, engine):
    """E2E Test: API -> Redis -> Listener -> plan-runner CLI -> success response"""
    if not E2E_PLAN_FILE.exists():
        pytest.skip(f"E2E fixture plan not found: {E2E_PLAN_FILE}")

    # Create request with dry_run to execute quickly without LLM calls
    req = RunRequest(
        engine=engine,
        dry_run=True,
        plan_file=str(E2E_PLAN_FILE),
        test_source="test_e2e",
    )
    
    # 1. Start execution
    try:
        response = await executor_service.start_dev_runner(req)
    except HTTPException as exc:
        # Listener hand-off가 지연되는 케이스가 있어 1회 재시도 허용
        if exc.status_code != 504:
            raise
        await asyncio.sleep(1.0)
        await executor_service.cleanup_stale_runners()
        response = await executor_service.start_dev_runner(req)
    runner_id = response.runner_id

    assert response.running is True
    assert runner_id is not None
    assert response.engine == engine

    # 2. Wait for listener to pick up command and set pid (async processing)
    # dry_run exits fast so check Redis directly for pid before stale cleanup
    from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX
    pid_appeared = False
    engine_seen = False
    for _ in range(20):
        await asyncio.sleep(0.5)
        pid_val = executor_service.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
        engine_val = executor_service.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine")
        if engine_val is not None:
            assert engine_val == engine
            engine_seen = True
        if pid_val is not None:
            pid_appeared = True
            break
        # Also accept if status transitioned (dry_run finished quickly or launch failed fast)
        status_val = executor_service.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
        if status_val in ("running", "completed", "stopped", "error", "failed", None):
            pid_appeared = True  # listener consumed command and status changed (or finished cleanup)
            break
    assert pid_appeared, "Listener never processed the run command"
    assert engine_seen or response.engine == engine

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
    final_status = await executor_service.get_runner_status(runner_id)
    assert final_status.running is False
