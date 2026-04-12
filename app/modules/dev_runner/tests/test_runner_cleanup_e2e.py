"""T4: plan-runner cleanup 후 monitor-page API 상태 반영 검증

wtools cli.py의 _cleanup_redis_state() 수정(per-runner 키 정리 추가)이
monitor-page API에 올바르게 반영되는지 cross-project 검증.

cleanup 시뮬레이션:
  - status=stopped SET
  - SREM active_runners
  - EXPIRE per-runner 키
→ GET /api/v1/dev-runner/status → running: false
"""
import pytest
import fakeredis
import fakeredis.aioredis
from datetime import datetime
from unittest.mock import patch

from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.services.event_service import EventService, RUNNER_KEY_PREFIX
from app.modules.dev_runner.services.event_payload import build_status_payload

ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_TTL = 86400


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_executor_redis():
    """executor_service의 Redis를 fakeredis로 교체"""
    fake_sync = fakeredis.FakeRedis(decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(executor_service, 'redis_client', fake_sync), \
         patch.object(executor_service, 'async_redis', fake_async):
        yield {"async": fake_async, "sync": fake_sync}


# ─── T4 TC ──────────────────────────────────────────────────────────────────

class TestRunnerCleanupE2E:
    """wtools _cleanup_redis_state() 수정 후 monitor-page API 상태 반영 검증"""

    async def test_cleanup_removes_from_active_and_status_api_returns_not_running(
        self, client, mock_executor_redis
    ):
        """T4-1: cleanup 시뮬레이션 후 GET /status → running=False

        수정 전 동작 (버그):
          - active_runners에 runner_id 잔존 + status="running" → running=True

        수정 후 기대:
          - status="stopped" + SREM active_runners → smembers 빈 set → running=False
        """
        fake_sync = mock_executor_redis["sync"]
        fake_async = mock_executor_redis["async"]
        rid = "cleanup-e2e-01"
        now = datetime.now().isoformat()

        # 실행 중 상태 등록 (get_process_status()가 async_redis를 사용하므로 fake_async에 설정)
        await fake_async.set("plan-runner:listener:heartbeat", now)
        await fake_async.sadd(ACTIVE_RUNNERS_KEY, rid)
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", "99999")
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file", "fix-test.md")

        with patch.object(executor_service, "_is_pid_alive", return_value=True):
            response = await client.get("/api/v1/dev-runner/status")
        assert response.json()["running"] is True, "사전 조건: 실행 중 상태여야 함"

        # wtools _cleanup_redis_state() 수정 후 동작 시뮬레이션
        # 1. status = stopped
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
        # 2. EXPIRE per-runner 키 (즉시 삭제 X, TTL 설정)
        for suffix in ("status", "pid", "plan_file"):
            await fake_async.expire(f"{RUNNER_KEY_PREFIX}:{rid}:{suffix}", RECENT_RUNNERS_TTL)
        # 3. SREM active_runners ← 이 수정이 핵심 (수정 전에는 이 부분이 없었음)
        await fake_async.srem(ACTIVE_RUNNERS_KEY, rid)

        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        assert response.json()["running"] is False, \
            "cleanup 후 SREM active_runners → smembers 빈 set → running=False 이어야 함"

    async def test_status_keeps_cc_codex_engine_for_running_runner(self, client, mock_executor_redis):
        """cc-codex 엔진으로 실행 중인 runner 상태가 API 응답에 유지되는지 확인"""
        fake_async = mock_executor_redis["async"]
        rid = "cleanup-e2e-engine-cc-codex"
        now = datetime.now().isoformat()

        await fake_async.set("plan-runner:listener:heartbeat", now)
        await fake_async.sadd(ACTIVE_RUNNERS_KEY, rid)
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", "88888")
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:engine", "cc-codex")

        with patch.object(executor_service, "_is_pid_alive", return_value=True):
            response = await client.get("/api/v1/dev-runner/status")

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["engine"] == "cc-codex"

    async def test_cleanup_event_service_emits_stopped_status(self, mock_executor_redis):
        """T4-2: cleanup 후 EventService._build_status_payload() → status=stopped

        cleanup 시나리오에서 status 키가 'stopped'로 설정되면
        _build_status_payload()의 status 필드가 'stopped'를 반환하는지 확인.
        (plan_file 키가 없을 때는 stopped 상태에서 None 반환 — 프론트엔드 title 덮어씌움 방지)
        """
        fake_sync = mock_executor_redis["sync"]
        rid = "cleanup-event-01"

        # cleanup 시뮬레이션: status=stopped, plan_file 키 없음
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
        # plan_file 키는 설정하지 않음 (cleanup 후 TTL 만료 or 처음부터 없는 경우)
        fake_sync.srem(ACTIVE_RUNNERS_KEY, rid)

        svc = EventService.__new__(EventService)
        svc._sync = fake_sync
        svc._async = fakeredis.aioredis.FakeRedis(decode_responses=True)

        payload = build_status_payload(svc._sync, rid)

        assert payload is not None
        assert payload["status"] == "stopped", \
            f"cleanup 후 status가 'stopped'여야 함 (현재: {payload['status']})"
        assert payload["plan_file"] is None, \
            "stopped 상태 + plan_file 키 없음 → plan_file=None (프론트엔드 title 덮어씌움 방지)"
