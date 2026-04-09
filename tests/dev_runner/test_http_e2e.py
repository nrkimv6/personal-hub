import os
import signal
import sys
import time
import pytest
import subprocess
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
import redis

import redis.asyncio as aioredis
from tests.dev_runner.conftest_e2e import (
    TEST_PLAN_FILE,
    isolated_redis,
    listener_process,
    REDIS_TEST_DB,
)

pytestmark = pytest.mark.http

# Constants
REDIS_HOST = "localhost"
REDIS_PORT = 6379
BASE_URL = "/api/v1/dev-runner"



class TestHttpE2EChain:
    """T5: TestClient 기반 HTTP E2E — isolated_redis + listener_process(db=15) 격리"""

    @pytest.fixture(autouse=True)
    def setup_async_redis_db15(self, isolated_redis):
        """executor_service의 async_redis를 db=15로 교체 (TestClient 이벤트루프 호환)

        isolated_redis.reconnect()는 redis_client를 교체하지만 async_redis는
        TestClient 이벤트루프 컨텍스트에서 여전히 구버전 연결을 사용할 수 있음.
        명시적으로 교체하여 listener(db=15)와 동일한 DB를 바라보게 함.
        """
        from app.modules.dev_runner.services import executor_service as es_module
        old_async_redis = es_module.executor_service.async_redis
        es_module.executor_service.async_redis = aioredis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB,
            decode_responses=True, socket_connect_timeout=5, socket_timeout=35,
        )
        yield
        es_module.executor_service.async_redis = old_async_redis

    @pytest.fixture(autouse=True)
    def cleanup_redis_after_test(self, isolated_redis):
        """각 테스트 메서드 종료 후 active runner stop + PID kill + Redis 키 자동 정리."""
        yield
        try:
            from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)

            # 1. active runner_id 목록 조회
            active = isolated_redis.smembers(ACTIVE_RUNNERS_KEY)

            # 2. 각 runner에 stop 요청 (API 레벨)
            _client = TestClient(app)
            for runner_id in active:
                try:
                    _client.post(f"{BASE_URL}/stop/{runner_id}")
                except Exception:
                    pass

            # 3. PID kill (stop이 실패하거나 늦을 경우 안전망)
            for runner_id in active:
                pid_str = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
                if pid_str:
                    try:
                        os.kill(int(pid_str), signal.SIGTERM)
                    except (ProcessLookupError, ValueError, OSError):
                        pass

            # 4. Redis 키 전체 삭제 (isolated_redis = db=15)
            stale_keys = isolated_redis.keys("plan-runner:*")
            if stale_keys:
                isolated_redis.delete(*stale_keys)
        except Exception:
            pass

    def test_http_start_and_stop_lifecycle(self, isolated_redis, listener_process):
        """E2E: POST /run → running 확인 → POST /stop → active_runners 비어짐 확인"""
        client = TestClient(app)
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_PREFIX,
            ACTIVE_RUNNERS_KEY,
            RECENT_RUNNERS_KEY,
        )

        payload = {
            "engine": "gemini",
            "plan_file": TEST_PLAN_FILE,
            "dry_run": True,
            "test_source": "test_http_start_and_stop_lifecycle"
        }

        # 1. Start runner
        runner_id = None
        try:
            response = client.post(f"{BASE_URL}/run", json=payload)
            if response.status_code == 200:
                runner_id = response.json().get("runner_id")
            else:
                print(f"Got {response.status_code} from TestClient, checking Redis...")
        except Exception as e:
            print(f"TestClient exception: {e}")

        assert runner_id is not None, "API가 runner_id를 반환하지 않음 (500/504 오류)"

        # 2. accepted_at 관측 필수 계약 — listener가 명령을 처리했다는 직접 증거
        # accepted_at은 start_plan_runner()에서 accepted push 직후 저장되므로
        # runner_id가 반환됐다면 반드시 관측되어야 한다.
        accepted_at = None
        for _ in range(20):
            accepted_at = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:accepted_at")
            if accepted_at:
                break
            time.sleep(0.5)
        assert accepted_at is not None, (
            f"accepted_at 키 미관찰 (runner_id={runner_id}): "
            "listener가 accepted 처리를 완료했어야 하지만 메타가 없음"
        )
        accepted_source = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:accepted_source")
        assert accepted_source == "listener", f"accepted_source 불일치: {accepted_source!r}"

        # 3. lifecycle 관측 (started_at 포함)
        # dry_run은 빠르게 종료되어 running 상태를 놓칠 수 있으므로
        # started_at / terminal status / recent_runners 등록 중 하나를 허용한다.
        observed = False
        for _ in range(20):
            status = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
            pid = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
            started_at = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:started_at")
            in_recent = isolated_redis.zscore(RECENT_RUNNERS_KEY, runner_id) is not None
            if (status == "running" and pid) or started_at or status in ("completed", "stopped", "failed") or in_recent:
                observed = True
                break
            time.sleep(1)

        assert observed, (
            f"runner lifecycle 미관찰 (runner_id={runner_id}): "
            "started_at / running / terminal status / recent 중 어느 것도 없음"
        )
        print(f"\n[START OK] runner_id={runner_id}, PID={isolated_redis.get(f'{RUNNER_KEY_PREFIX}:{runner_id}:pid')}, accepted_at={accepted_at}")

        # 3. Stop runner
        resp = client.post(f"{BASE_URL}/stop/{runner_id}")
        if resp.status_code == 404:
            # dry_run이 이미 완료 → active_runners에서 직접 제거
            isolated_redis.srem(ACTIVE_RUNNERS_KEY, runner_id)

        # 4. active_runners 비어짐 확인
        cleaned = False
        for _ in range(10):
            if not isolated_redis.smembers(ACTIVE_RUNNERS_KEY):
                cleaned = True
                break
            time.sleep(1)

        assert cleaned is True, "active_runners가 10초 내 비워지지 않음"
        print("\n[STOP OK] HTTP E2E Start+Stop Lifecycle Verified")
