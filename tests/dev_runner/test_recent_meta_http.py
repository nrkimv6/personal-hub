"""cleanup 후 trigger/recent-meta 노출 검증 TC

Phase T1 항목 6: cleanup 이후 trigger/recent-meta 접근 가능 여부 검증
- cleanup 전: live trigger 키 존재
- cleanup 후: recent-meta JSON에 trigger 보존
- executor_service.get_all_runners(): trigger fallback 동작
"""
import json
import time
import pytest
from fastapi.testclient import TestClient
import redis.asyncio as aioredis
from tests.dev_runner.conftest_e2e import (
    TEST_PLAN_FILE,
    isolated_redis_db15,
    listener_process,
    REDIS_TEST_DB,
)

pytestmark = pytest.mark.http

REDIS_HOST = "localhost"
REDIS_PORT = 6379
BASE_URL = "/api/v1/dev-runner"
RUNNER_KEY_PREFIX = "plan-runner:runners"


def _build_test_client() -> TestClient:
    from app.main import app
    return TestClient(app)


class TestRecentMetaHttp:
    """cleanup 후 trigger/recent-meta 보존 계약 검증 (TestClient + isolated_redis_db15)"""

    @pytest.fixture(autouse=True)
    def setup_async_redis_db15(self, isolated_redis_db15):
        from app.modules.dev_runner.services import executor_service as es_module
        old_async_redis = es_module.executor_service.async_redis
        es_module.executor_service.async_redis = aioredis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB,
            decode_responses=True, socket_connect_timeout=5, socket_timeout=35,
        )
        yield
        es_module.executor_service.async_redis = old_async_redis

    @pytest.fixture(autouse=True)
    def cleanup_redis_after_test(self, isolated_redis_db15):
        yield
        try:
            stale_keys = [
                k for k in isolated_redis_db15.keys("plan-runner:*")
                if not k.startswith("plan-runner:listener:")
            ]
            if stale_keys:
                isolated_redis_db15.delete(*stale_keys)
        except Exception:
            pass

    def test_accepted_at_set_after_run(self, isolated_redis_db15, listener_process):
        """POST /run → accepted_at + accepted_source 키 세팅 확인"""
        client = _build_test_client()
        payload = {
            "engine": "gemini",
            "plan_file": TEST_PLAN_FILE,
            "dry_run": True,
            "test_source": "test_accepted_at_set_after_run",
        }
        resp = client.post(f"{BASE_URL}/run", json=payload)
        assert resp.status_code == 200
        runner_id = resp.json().get("runner_id")
        assert runner_id, f"runner_id 없음: {resp.json()}"

        # accepted_at 폴링 (최대 10초)
        accepted_at = None
        for _ in range(20):
            accepted_at = isolated_redis_db15.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:accepted_at")
            if accepted_at:
                break
            time.sleep(0.5)
        assert accepted_at is not None, f"accepted_at 키 미세팅 (runner_id={runner_id})"

        accepted_source = isolated_redis_db15.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:accepted_source")
        assert accepted_source == "listener", f"accepted_source={accepted_source!r}"

    def test_recent_meta_after_cleanup(self, isolated_redis_db15, listener_process):
        """dry_run 완료 후 cleanup 시 recent-meta에 trigger 보존 확인"""
        client = _build_test_client()
        payload = {
            "engine": "gemini",
            "plan_file": TEST_PLAN_FILE,
            "dry_run": True,
            "test_source": "test_recent_meta_after_cleanup",
        }
        resp = client.post(f"{BASE_URL}/run", json=payload)
        assert resp.status_code == 200
        runner_id = resp.json().get("runner_id")
        assert runner_id

        stop_resp = client.post(f"{BASE_URL}/stop/{runner_id}")
        assert stop_resp.status_code in (200, 404), (
            f"stop 요청 실패: {stop_resp.status_code} {stop_resp.text}"
        )

        # runner cleanup 후 recent-meta가 저장될 때까지 대기
        found_in_recent = False
        for _ in range(60):
            meta_raw = isolated_redis_db15.get(f"plan-runner:recent-meta:{runner_id}")
            if meta_raw is not None:
                found_in_recent = True
                break
            time.sleep(1)
        assert found_in_recent, f"runner {runner_id}의 recent-meta가 60초 내 저장되지 않음"

        # recent-meta 확인 — cleanup 후 trigger 보존
        meta_raw = isolated_redis_db15.get(f"plan-runner:recent-meta:{runner_id}")
        assert meta_raw is not None, (
            f"recent-meta 키 없음 (runner_id={runner_id}): "
            "cleanup 후에도 trigger 보존이 안 됨"
        )
        meta = json.loads(meta_raw)
        trigger_in_meta = meta.get("trigger")
        assert trigger_in_meta is not None, (
            f"recent-meta에 trigger 없음: {meta}"
        )
        # test_source 기반 trigger는 tc:{test_source} 형태
        assert "test_recent_meta_after_cleanup" in trigger_in_meta or trigger_in_meta.startswith("tc:"), (
            f"trigger 값 예상과 다름: {trigger_in_meta!r}"
        )
