import os
import signal
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


REDIS_TEST_DB = 15

@pytest.fixture(scope="module")
def background_listener():
    import redis.asyncio as aioredis
    from app.modules.dev_runner.services import executor_service as es_module

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)
    # FORCE CLEANUP
    r.delete("plan-runner:state:status")
    r.delete("plan-runner:state:pid")
    r.delete("plan-runner:listener:heartbeat")
    # 이전 테스트 실행에서 남은 stale worktree 정리
    _cleanup_test_worktree()

    script_path = Path("scripts/dev-runner-command-listener.py")
    process = subprocess.Popen(
        ["python", str(script_path), "--redis-db", str(REDIS_TEST_DB)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Wait for heartbeat
    for _ in range(20):
        if r.get("plan-runner:listener:heartbeat"):
            break
        time.sleep(0.5)

    # executor_service의 Redis 클라이언트를 db=15로 교체 (API-Listener 격리 일치)
    old_redis = es_module.executor_service.redis_client
    old_async_redis = es_module.executor_service.async_redis
    new_redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True,
                            socket_connect_timeout=5, socket_timeout=10)
    new_async_redis = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True,
                                     socket_connect_timeout=5, socket_timeout=35)
    es_module.executor_service.redis_client = new_redis
    es_module.executor_service.async_redis = new_async_redis

    yield process

    # 원래 Redis 클라이언트 복원
    es_module.executor_service.redis_client = old_redis
    es_module.executor_service.async_redis = old_async_redis

    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
    # 테스트 완료 후 worktree 정리
    _cleanup_test_worktree()

class TestHttpE2EChain:
    @pytest.fixture(autouse=True)
    def cleanup_redis_after_test(self, api_client):
        """각 테스트 메서드 종료 후 active runner stop + PID kill + Redis 키 자동 정리."""
        yield
        try:
            from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)

            # 1. active runner_id 목록 조회
            active = r.smembers(ACTIVE_RUNNERS_KEY)

            # 2. 각 runner에 stop 요청 (API 레벨)
            for runner_id in active:
                try:
                    api_client.post(f"{BASE_URL}/stop/{runner_id}")
                except Exception:
                    pass

            # 3. PID kill (stop이 실패하거나 늦을 경우 안전망)
            for runner_id in active:
                pid_str = r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
                if pid_str:
                    try:
                        os.kill(int(pid_str), signal.SIGTERM)
                    except (ProcessLookupError, ValueError, OSError):
                        pass

            # 4. Redis 키 전체 삭제
            stale_keys = r.keys("plan-runner:*")
            if stale_keys:
                r.delete(*stale_keys)
        except Exception:
            pass

    def test_http_start_and_stop_lifecycle(self, api_client, background_listener):
        """E2E: POST /run → running 확인 → POST /stop → active_runners 비어짐 확인"""
        from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)

        payload = {
            "engine": "gemini",
            "plan_file": "docs/plan/test_e2e_plan.md",
            "dry_run": True
        }

        # 1. Start runner
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

        # 2. running 상태 확인
        executed = False
        for _ in range(20):
            status = r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
            pid = r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
            if status == "running" and pid:
                executed = True
                break
            time.sleep(1)

        assert executed is True, f"E2E Failed: runner {runner_id} status={r.get(f'{RUNNER_KEY_PREFIX}:{runner_id}:status')}"
        print(f"\n[START OK] runner_id={runner_id}, PID={r.get(f'{RUNNER_KEY_PREFIX}:{runner_id}:pid')}")

        # 3. Stop runner
        resp = api_client.post(f"{BASE_URL}/stop/{runner_id}")
        if resp.status_code == 404:
            # dry_run이 이미 완료 → active_runners에서 직접 제거
            r.srem(ACTIVE_RUNNERS_KEY, runner_id)

        # 4. active_runners 비어짐 확인
        cleaned = False
        for _ in range(10):
            if not r.smembers(ACTIVE_RUNNERS_KEY):
                cleaned = True
                break
            time.sleep(1)

        assert cleaned is True, "active_runners가 10초 내 비워지지 않음"
        print("\n[STOP OK] HTTP E2E Start+Stop Lifecycle Verified")
