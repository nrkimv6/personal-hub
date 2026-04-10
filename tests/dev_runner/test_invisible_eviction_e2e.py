"""test_invisible_eviction_e2e.py — invisible runner eviction E2E 테스트 (T4)

cleanup-stale API 호출 시 invisible runner(trigger=None)가 RECENT에서 제거되는지 검증.

/merge-test 스킬이 main 머지 후 실행.
"""
import time
import pytest
import fakeredis
import fakeredis.aioredis
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.modules.dev_runner.services.executor_service import (
    executor_service,
    ACTIVE_RUNNERS_KEY,
    RECENT_RUNNERS_KEY,
    RUNNER_KEY_PREFIX,
)

pytestmark = pytest.mark.http


@pytest.fixture()
def client_with_fake_redis():
    """TestClient + fakeredis 주입 fixture"""
    from app.main import app

    server = fakeredis.FakeServer()
    fake_sync = fakeredis.FakeRedis(server=server, decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_session_local = MagicMock(return_value=mock_db)

    with patch.object(executor_service, 'redis_client', fake_sync), \
         patch.object(executor_service, 'async_redis', fake_async), \
         patch('app.database.SessionLocal', mock_session_local):
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, fake_sync


class TestCleanupStaleInvisibleEvictionE2E:

    def test_cleanup_stale_e2e_invisible_eviction(self, client_with_fake_redis):
        """T4: cleanup-stale API → invisible runner(trigger=None, status='stopped', TTL 내) 정리 검증

        1. fakeredis에 invisible runner 등록 (RECENT set, TTL 내)
        2. POST /api/v1/dev-runner/runners/cleanup-stale 호출
        3. 응답에 cleaned_recent ≥ 1 검증
        4. GET /api/v1/dev-runner/runners 응답에서 invisible runner 미포함 검증
        """
        client, fake = client_with_fake_redis
        invisible_rid = "e2e-invisible-runner-001"
        visible_rid = "e2e-visible-runner-001"

        # invisible runner (trigger 없음) — TTL 내 stopped runner (이전: 보존됨, 이후: 즉시 정리)
        fake.zadd(RECENT_RUNNERS_KEY, {invisible_rid: time.time()})
        fake.set(f"{RUNNER_KEY_PREFIX}:{invisible_rid}:status", "stopped")
        # trigger 미설정 = invisible

        # visible runner — 비교용
        fake.zadd(RECENT_RUNNERS_KEY, {visible_rid: time.time()})
        fake.set(f"{RUNNER_KEY_PREFIX}:{visible_rid}:status", "stopped")
        fake.set(f"{RUNNER_KEY_PREFIX}:{visible_rid}:trigger", "user")
        fake.set(f"{RUNNER_KEY_PREFIX}:{visible_rid}:plan_file", "docs/plan/test.md")

        # 1. cleanup-stale API 호출
        response = client.post("/api/v1/dev-runner/runners/cleanup-stale")
        assert response.status_code == 200, f"cleanup-stale 실패: {response.text}"

        result = response.json()
        assert result.get("cleaned_recent", 0) >= 1, (
            f"invisible runner가 cleaned_recent에 포함되어야 함. 실제: {result}"
        )

        # 2. GET /runners 에서 invisible runner 미포함 확인
        runners_resp = client.get("/api/v1/dev-runner/runners")
        assert runners_resp.status_code == 200, f"GET /runners 실패: {runners_resp.text}"
        runner_ids = [r["runner_id"] for r in runners_resp.json()]

        assert invisible_rid not in runner_ids, (
            f"cleanup-stale 후 invisible runner({invisible_rid})가 /runners 응답에 포함되면 안 됨"
        )
        assert visible_rid in runner_ids, (
            f"visible runner({visible_rid})는 /runners 응답에 포함되어야 함"
        )
