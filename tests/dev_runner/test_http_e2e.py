import json
import time
import pytest
import subprocess
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
import redis

pytestmark = pytest.mark.http

# Constants
REDIS_HOST = "localhost"
REDIS_PORT = 6379
BASE_URL = "/api/v1/dev-runner"

@pytest.fixture(scope="module")
def api_client():
    return TestClient(app)

def _cleanup_test_worktree():
    """테스트용 worktree/branch 정리 (중복 실행 방지)"""
    try:
        worktree_path = Path(".worktrees/test_e2e_plan")
        subprocess.run(
            ["git", "worktree", "remove", str(worktree_path), "--force"],
            capture_output=True, cwd=str(Path("."))
        )
    except Exception:
        pass
    try:
        subprocess.run(
            ["git", "branch", "-D", "plan/test_e2e_plan"],
            capture_output=True, cwd=str(Path("."))
        )
    except Exception:
        pass


@pytest.fixture(scope="module")
def background_listener():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    # FORCE CLEANUP
    r.delete("plan-runner:state:status")
    r.delete("plan-runner:state:pid")
    r.delete("plan-runner:listener:heartbeat")
    # 이전 테스트 실행에서 남은 stale worktree 정리
    _cleanup_test_worktree()
    
    script_path = Path("scripts/dev-runner-command-listener.py")
    process = subprocess.Popen(
        ["python", str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for heartbeat
    for _ in range(20):
        if r.get("plan-runner:listener:heartbeat"):
            break
        time.sleep(0.5)
    
    yield process
    
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
    # 테스트 완료 후 worktree 정리
    _cleanup_test_worktree()

class TestHttpE2EChain:
    def test_http_start_to_process_execution(self, api_client, background_listener):
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

        payload = {
            "engine": "gemini",
            "plan_file": "docs/plan/test_e2e_plan.md",
            "dry_run": True
        }

        runner_id = None
        try:
            response = api_client.post(f"{BASE_URL}/run", json=payload)
            if response.status_code == 200:
                runner_id = response.json().get("runner_id")
            else:
                print(f"Got {response.status_code} from TestClient, checking Redis...")
        except Exception as e:
            print(f"TestClient exception: {e}")

        assert runner_id is not None, "API가 runner_id를 반환하지 않음 (500/504 오류)"

        # VERIFY REDIS — per-runner 키 확인
        from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX
        executed = False
        for _ in range(20):
            status = r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
            pid = r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
            if status == "running" and pid:
                executed = True
                break
            time.sleep(1)

        assert executed is True, f"E2E Failed: runner {runner_id} status={r.get(f'{RUNNER_KEY_PREFIX}:{runner_id}:status')}"
        print(f"\n[SUCCESS] HTTP E2E Start Chain Verified (runner_id: {runner_id}, PID: {r.get(f'{RUNNER_KEY_PREFIX}:{runner_id}:pid')})")

    def test_http_stop_to_process_cleanup(self, api_client, background_listener):
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY

        # active runners 확인 후 stop
        active = r.smembers(ACTIVE_RUNNERS_KEY)
        for runner_id in active:
            try:
                resp = api_client.post(f"{BASE_URL}/stop/{runner_id}")
                # 404: 이미 종료됨 → active_runners에서 직접 제거 (stale 정리)
                if resp.status_code == 404:
                    r.srem(ACTIVE_RUNNERS_KEY, runner_id)
            except Exception:
                pass

        # active_runners가 비어질 때까지 대기 (running 중인 runner는 listener가 정리)
        cleaned = False
        for _ in range(10):
            if not r.smembers(ACTIVE_RUNNERS_KEY):
                cleaned = True
                break
            time.sleep(1)

        assert cleaned is True
        print("\n[SUCCESS] HTTP E2E Stop Chain Verified")
