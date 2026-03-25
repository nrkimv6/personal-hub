"""실행 제어 API 테스트 - fakeredis + patch.object 적용"""

import json
from unittest.mock import patch, AsyncMock
from datetime import datetime

import pytest
import redis
import fakeredis
import fakeredis.aioredis

from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.services.state import get_state

RESULTS_KEY = "plan-runner:command_results"


@pytest.fixture(autouse=True)
def mock_executor_redis():
    """executor_service의 async_redis와 redis_client를 fakeredis로 교체"""
    fake_sync = fakeredis.FakeRedis(decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(executor_service, 'redis_client', fake_sync), \
         patch.object(executor_service, 'async_redis', fake_async):
        yield {"async": fake_async, "sync": fake_sync}


class TestGetStatus:
    async def test_get_status_not_running(self, client):
        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert data["pid"] is None

    async def test_get_status_running(self, client, mock_executor_redis):
        fake_async = mock_executor_redis["async"]
        rid = "test-runner-running"
        await fake_async.set("plan-runner:listener:heartbeat", "2026-02-18T10:00:00")
        await fake_async.sadd("plan-runner:active_runners", rid)
        await fake_async.set(f"plan-runner:runners:{rid}:status", "running")
        await fake_async.set(f"plan-runner:runners:{rid}:pid", "12345")
        await fake_async.set(f"plan-runner:runners:{rid}:plan_file", "test.md")

        from app.modules.dev_runner.services.executor_service import executor_service as svc
        with patch.object(svc, "_is_pid_alive", return_value=True):
            response = await client.get("/api/v1/dev-runner/status")

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["pid"] == 12345
        assert data["listener_alive"] is True

    async def test_status_after_cleanup(self, client, mock_executor_redis):
        """TC-R (Right): 정상 종료 후 _cleanup_redis_state() → running=False"""
        from unittest.mock import patch
        fake_sync = mock_executor_redis["sync"]
        RUNNER_KEY_PREFIX = "plan-runner:runners"
        ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
        rid = "test-runner-cleanup"
        fake_sync.set("plan-runner:listener:heartbeat", "2026-02-27T10:00:00")
        fake_sync.sadd(ACTIVE_RUNNERS_KEY, rid)
        # Fix 2 결과: cleanup 후 status="stopped" (삭제가 아님)
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")

        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert fake_sync.get(f"{RUNNER_KEY_PREFIX}:{rid}:status") == "stopped"

    async def test_get_status_running_with_valid_pid(self, client, mock_executor_redis):
        """HTTP-2: PID 살아있음 mock → running=True, pid!=None"""
        fake_async = mock_executor_redis["async"]
        RUNNER_KEY_PREFIX = "plan-runner:runners"
        ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
        rid = "test-runner-pid"
        await fake_async.set("plan-runner:listener:heartbeat", "2026-02-27T10:00:00")
        await fake_async.sadd(ACTIVE_RUNNERS_KEY, rid)
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", "55555")

        from app.modules.dev_runner.services.executor_service import executor_service as svc
        with patch.object(svc, "_is_pid_alive", return_value=True):
            response = await client.get("/api/v1/dev-runner/status")

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["pid"] is not None

    async def test_get_status_after_cleanup_deleted_key(self, client, mock_executor_redis):
        """HTTP-3: status 키 없음(None) + heartbeat 있음 → running=False (Fix 2 회귀 방지)"""
        fake_sync = mock_executor_redis["sync"]
        ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
        RUNNER_KEY_PREFIX = "plan-runner:runners"
        rid = "test-runner-deleted"
        fake_sync.set("plan-runner:listener:heartbeat", "2026-02-27T10:00:00")
        fake_sync.sadd(ACTIVE_RUNNERS_KEY, rid)
        # status 키 없음 (삭제된 상태) — old behavior가 이를 "running"으로 복원하던 버그
        # Fix 1+2 이후에는 None 상태가 running=False를 반환해야 함
        # (status가 None이면 "running"이 아니므로 running=False)

        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False


class TestGetStatusListenerAlive:
    """listener_alive 필드 테스트"""

    async def test_listener_alive_true_when_heartbeat_exists(self, client, mock_executor_redis):
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", "2026-02-19T10:00:00")
        # running=False이지만 listener는 살아있음

        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        data = response.json()
        assert data["listener_alive"] is True
        assert data["running"] is False

    async def test_listener_alive_false_when_no_heartbeat(self, client, mock_executor_redis):
        # heartbeat 없음

        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        data = response.json()
        assert data["listener_alive"] is False
        assert data["running"] is False

    async def test_running_true_with_heartbeat(self, client, mock_executor_redis):
        fake_async = mock_executor_redis["async"]
        rid = "test-runner-heartbeat"
        await fake_async.set("plan-runner:listener:heartbeat", "2026-02-19T10:00:00")
        await fake_async.sadd("plan-runner:active_runners", rid)
        await fake_async.set(f"plan-runner:runners:{rid}:status", "running")
        await fake_async.set(f"plan-runner:runners:{rid}:pid", "12345")

        from app.modules.dev_runner.services.executor_service import executor_service as svc
        with patch.object(svc, "_is_pid_alive", return_value=True):
            response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        data = response.json()
        assert data["listener_alive"] is True
        assert data["running"] is True
        assert data["pid"] == 12345

    async def test_stale_running_without_heartbeat(self, client, mock_executor_redis):
        """running=True이지만 heartbeat 없음 → stale 정리 → running=False"""
        fake_sync = mock_executor_redis["sync"]
        fake_sync.set("plan-runner:state:status", "running")
        fake_sync.set("plan-runner:state:pid", "12345")
        # heartbeat 없음

        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        data = response.json()
        assert data["listener_alive"] is False
        assert data["running"] is False
        # TC-E: heartbeat 없이 running=False 반환 확인 (stale 정리 검증)
        # 새 코드는 ACTIVE_RUNNERS_KEY 기반으로 동작하므로, 이 테스트에서 old state key는 검사 대상 아님

    async def test_status_stopped_during_heartbeat_window(self, client, mock_executor_redis):
        """TC-B (Boundary): heartbeat 살아있어도 status=stopped이면 running=False"""
        fake_async = mock_executor_redis["async"]
        RUNNER_KEY_PREFIX = "plan-runner:runners"
        ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
        rid = "test-runner-1"
        await fake_async.set("plan-runner:listener:heartbeat", "2026-02-27T10:00:00")
        await fake_async.sadd(ACTIVE_RUNNERS_KEY, rid)
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", "12345")

        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert data["listener_alive"] is True


class TestStartRun:
    async def test_start_run_success(self, client, mock_executor_redis):
        """단일 Plan start → running=True, plan_file 정상 반환"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()

        await fake_async.set("plan-runner:listener:heartbeat", now)
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, 'brpop', new=AsyncMock(return_value=brpop_result)):
            # per-runner 키는 runner_id가 랜덤이므로 pid는 None으로 검증
            await fake_async.set("plan-runner:state:plan_file", "test-plan.md")
            await fake_async.set("plan-runner:state:start_time", now)

            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md"
            })

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["plan_file"] == "test-plan.md"

    async def test_start_run_plan_file_fallback_from_request(self, client, mock_executor_redis):
        """Redis에 plan_file 키가 아직 없을 때 request.plan_file로 fallback되는지 확인"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()

        await fake_async.set("plan-runner:listener:heartbeat", now)
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, 'brpop', new=AsyncMock(return_value=brpop_result)):
            await fake_async.set("plan-runner:state:pid", "12345")
            # plan_file 키 미세팅 (race condition 시뮬레이션)
            await fake_async.set("plan-runner:state:start_time", now)

            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "docs/plan/2026-02-27_test.md"
            })

        assert response.status_code == 200
        data = response.json()
        assert data["plan_file"] == "docs/plan/2026-02-27_test.md"

    async def test_double_start_returns_409(self, client, mock_executor_redis):
        """max_concurrent_runners(3) 초과 시 429 반환 — 실질적 duplicate-start 방지"""
        from app.modules.dev_runner.services.executor_service import ACTIVE_RUNNERS_KEY, RUNNER_KEY_PREFIX
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())
        # 3개 runner 추가 (max_concurrent_runners=3 초과 → 429)
        for i in range(3):
            rid = f"existing-runner-{i}"
            await fake_async.sadd(ACTIVE_RUNNERS_KEY, rid)
            await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
            await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", str(10000 + i))

        with patch.object(executor_service, '_is_pid_alive', return_value=True):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md"
            })
        assert response.status_code == 429

    async def test_start_redis_down_503(self, client, mock_executor_redis):
        # ConnectionError 테스트: ping에서 실패하도록 mock
        with patch.object(executor_service, 'async_redis') as mock_async:
            mock_async.ping = AsyncMock(side_effect=redis.ConnectionError("Connection refused"))
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test.md"
            })
        assert response.status_code == 503

    async def test_start_listener_not_running_503(self, client, mock_executor_redis):
        """listener heartbeat 없으면 503"""
        # heartbeat 키를 세팅하지 않음 → listener 미실행 판정
        response = await client.post("/api/v1/dev-runner/run", json={
            "plan_file": "test.md"
        })
        assert response.status_code == 503

    async def test_start_brpop_timeout_504(self, client, mock_executor_redis):
        fake_async = mock_executor_redis["async"]
        # listener heartbeat 세팅 (사전 확인 통과)
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())
        # status: not running (None), brpop: timeout → None 반환
        # fakeredis는 데이터 없을 때 brpop이 즉시 None 반환
        response = await client.post("/api/v1/dev-runner/run", json={
            "plan_file": "test.md"
        })
        assert response.status_code == 504

    async def test_start_run_fix_engine_stored_in_command(self, client, mock_executor_redis):
        """T4.1: fix_engine 필드가 Redis command에 포함되는지 확인"""
        fake_async = mock_executor_redis["async"]
        fake_sync = mock_executor_redis["sync"]
        now = datetime.now().isoformat()

        await fake_async.set("plan-runner:listener:heartbeat", now)
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, 'brpop', new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "fix_engine": "gemini",
            })

        assert response.status_code == 200
        # Redis command queue에 fix_engine이 포함됐는지 확인 (async_redis로 push됨)
        raw = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert len(raw) > 0, "command queue에 항목 없음"
        command = json.loads(raw[0])
        assert command.get("fix_engine") == "gemini", f"fix_engine 미포함: {command}"

    async def test_start_run_fix_engine_default_claude(self, client, mock_executor_redis):
        """T4.2: fix_engine 미전달 시 기본값 claude"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()

        await fake_async.set("plan-runner:listener:heartbeat", now)
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, 'brpop', new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
            })

        assert response.status_code == 200
        raw = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert len(raw) > 0, "command queue에 항목 없음"
        command = json.loads(raw[0])
        assert command.get("fix_engine") == "claude", f"fix_engine 기본값 오류: {command}"


class TestStopRun:
    async def test_stop_not_running_returns_404(self, client, mock_executor_redis):
        # fakeredis 빈 상태 → status None → not running → 404
        response = await client.post("/api/v1/dev-runner/stop")
        assert response.status_code == 404

    async def test_stop_running_process(self, client, mock_executor_redis):
        from app.modules.dev_runner.services.executor_service import ACTIVE_RUNNERS_KEY, RUNNER_KEY_PREFIX
        fake_async = mock_executor_redis["async"]
        rid = "stop-test-runner"
        await fake_async.set("plan-runner:listener:heartbeat", "2026-02-19T10:00:00")
        await fake_async.sadd(ACTIVE_RUNNERS_KEY, rid)
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", "55555")

        brpop_result = (f"plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Stopped"}))
        with patch.object(fake_async, 'brpop', new=AsyncMock(return_value=brpop_result)), \
             patch.object(executor_service, '_is_pid_alive', return_value=True):
            response = await client.post("/api/v1/dev-runner/stop")
        assert response.status_code == 200

    async def test_stop_redis_down_503(self, client, mock_executor_redis):
        # ConnectionError 테스트: ping에서 실패하도록 mock
        with patch.object(executor_service, 'async_redis') as mock_async:
            mock_async.ping = AsyncMock(side_effect=redis.ConnectionError("Connection refused"))
            response = await client.post("/api/v1/dev-runner/stop")
        assert response.status_code == 503


class TestResetState:
    """HTTP-4: POST /reset-state — stale "running" 강제 정리"""

    async def test_reset_clears_running_state(self, client, mock_executor_redis):
        """stale running 상태를 POST /reset-state로 정리 후 status 확인"""
        fake_sync = mock_executor_redis["sync"]
        RUNNER_KEY_PREFIX = "plan-runner:runners"
        ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
        rid = "stale-runner"
        fake_sync.sadd(ACTIVE_RUNNERS_KEY, rid)
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", "99999")

        response = await client.post("/api/v1/dev-runner/reset-state")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True

        # reset 후 status 조회 → running=False
        status_response = await client.get("/api/v1/dev-runner/status")
        assert status_response.status_code == 200
        assert status_response.json()["running"] is False
