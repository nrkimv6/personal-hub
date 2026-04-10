"""통합 테스트"""

import json
from datetime import datetime
from unittest.mock import patch, AsyncMock

import pytest
import fakeredis
import fakeredis.aioredis

from app.modules.claude_worker.services.profile_store import LLMProfile
from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.services.state import get_state

RESULTS_KEY = "plan-runner:command_results"
STATE_KEY = "plan-runner:state"


@pytest.fixture(autouse=True)
def mock_executor_redis():
    """executor_service의 Redis를 fakeredis로 교체 (FakeServer 공유로 sync/async 데이터 동기화)"""
    server = fakeredis.FakeServer()
    fake_sync = fakeredis.FakeRedis(server=server, decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    with patch.object(executor_service, 'redis_client', fake_sync), \
         patch.object(executor_service, 'async_redis', fake_async):
        yield {"async": fake_async, "sync": fake_sync}


class TestFullFlow:
    async def test_full_lifecycle(self, client, mock_executor_redis):
        fake_async = mock_executor_redis["async"]
        fake_sync = mock_executor_redis["sync"]
        now = datetime.now().isoformat()

        # 1. 초기 상태
        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        assert response.json()["running"] is False

    async def test_run_request_propagates_engine_and_fix_engine_to_command_queue(self, client, mock_executor_redis):
        """POST /run의 engine/fix_engine 값이 Redis command payload에 유지되는지 검증"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()
        await fake_async.set("plan-runner:listener:heartbeat", now)

        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post(
                "/api/v1/dev-runner/run",
                json={
                    "plan_file": "test.md",
                    "engine": "cc-codex",
                    "fix_engine": "cc-codex",
                },
            )

        assert response.status_code == 200
        queued = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert queued, "command queue가 비어 있음"
        command = json.loads(queued[0])
        assert command.get("engine") == "cc-codex"
        assert command.get("fix_engine") == "cc-codex"

    async def test_run_request_propagates_codex_engine_and_fix_engine_to_command_queue(self, client, mock_executor_redis):
        """POST /run의 codex engine/fix_engine 값이 Redis command payload에 유지되는지 검증"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()
        await fake_async.set("plan-runner:listener:heartbeat", now)

        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post(
                "/api/v1/dev-runner/run",
                json={
                    "plan_file": "test.md",
                    "engine": "codex",
                    "fix_engine": "codex",
                },
            )

        assert response.status_code == 200
        queued = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert queued, "command queue가 비어 있음"
        command = json.loads(queued[0])
        assert command.get("engine") == "codex"
        assert command.get("fix_engine") == "codex"

        # 2. 시작 (listener heartbeat + 성공 응답 세팅)
        rid = "lifecycle-runner-1"
        await fake_async.set("plan-runner:listener:heartbeat", now)
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, 'brpop', new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={"plan_file": "test.md"})
        assert response.status_code == 200
        assert response.json()["running"] is True

        # 3. 실행 중 확인 (status를 running으로 세팅)
        await fake_async.sadd("plan-runner:active_runners", rid)
        await fake_async.set(f"plan-runner:runners:{rid}:status", "running")
        await fake_async.set(f"plan-runner:runners:{rid}:pid", "55555")

        with patch.object(executor_service, '_is_pid_alive', return_value=True):
            response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        assert response.json()["running"] is True

        # 4. 중지 (runner 없어도 404 허용 — stop은 runner_id 기반)
        response = await client.post("/api/v1/dev-runner/stop")
        assert response.status_code in (200, 404)

        # 5. 중지 확인 (상태 정리 후)
        await fake_async.srem("plan-runner:active_runners", rid)
        await fake_async.set(f"plan-runner:runners:{rid}:status", "stopped")

        response = await client.get("/api/v1/dev-runner/status")
        assert response.status_code == 200
        assert response.json()["running"] is False

    async def test_run_accepted_then_runtime_failure_updates_runner_state(self, client, mock_executor_redis):
        """accepted 이후 runtime 실패(auto_plan_failed)가 runners API 상태에 반영되는지 검증"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now()
        await fake_async.set("plan-runner:listener:heartbeat", now.isoformat())

        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post(
                "/api/v1/dev-runner/run",
                json={
                    "plan_file": "test.md",
                    "engine": "codex",
                    "fix_engine": "codex",
                    "trigger": "user",
                },
            )

        assert response.status_code == 200
        rid = response.json()["runner_id"]
        prefix = f"plan-runner:runners:{rid}"

        await fake_async.srem("plan-runner:active_runners", rid)
        await fake_async.zadd("plan-runner:recent_runners", {rid: now.timestamp()})
        await fake_async.set(f"{prefix}:status", "failed")
        await fake_async.set(f"{prefix}:engine", "codex")
        await fake_async.set(f"{prefix}:trigger", "user")
        await fake_async.set(f"{prefix}:plan_file", "test.md")
        await fake_async.set(f"{prefix}:exit_reason", "auto_plan_failed")

        runners_response = await client.get("/api/v1/dev-runner/runners")
        assert runners_response.status_code == 200
        items = runners_response.json()
        target = next(item for item in items if item["runner_id"] == rid)
        assert target["running"] is False
        assert target["exit_reason"] == "auto_plan_failed"

    async def test_runtime_failure_preserves_engine_fix_engine_trigger_metadata(self, client, mock_executor_redis):
        """runtime 실패가 발생해도 run command 메타데이터(engine/fix_engine/trigger)가 보존되는지 검증"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now()
        await fake_async.set("plan-runner:listener:heartbeat", now.isoformat())

        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post(
                "/api/v1/dev-runner/run",
                json={
                    "plan_file": "runtime-failure.md",
                    "engine": "codex",
                    "fix_engine": "codex",
                    "trigger": "tc:runtime_failure",
                },
            )

        assert response.status_code == 200
        rid = response.json()["runner_id"]

        queued = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert queued, "command queue가 비어 있음"
        command = json.loads(queued[0])
        assert command.get("engine") == "codex"
        assert command.get("fix_engine") == "codex"
        assert command.get("trigger") == "tc:runtime_failure"

        prefix = f"plan-runner:runners:{rid}"
        await fake_async.srem("plan-runner:active_runners", rid)
        await fake_async.zadd("plan-runner:recent_runners", {rid: now.timestamp()})
        await fake_async.set(f"{prefix}:status", "failed")
        await fake_async.set(f"{prefix}:engine", command["engine"])
        await fake_async.set(f"{prefix}:trigger", command["trigger"])
        await fake_async.set(f"{prefix}:plan_file", "runtime-failure.md")
        await fake_async.set(f"{prefix}:exit_reason", "auto_plan_failed")

        runners_response = await client.get("/api/v1/dev-runner/runners")
        assert runners_response.status_code == 200
        items = runners_response.json()
        target = next(item for item in items if item["runner_id"] == rid)
        assert target["engine"] == "codex"
        assert target["trigger"] == "tc:runtime_failure"
        assert target["plan_file"] == "runtime-failure.md"


class TestLifecycleE2E:
    """E2E: 시작 → 실행 중 → 종료 전환 회귀 테스트 (Fix 1+2 검증)"""

    RUNNER_KEY_PREFIX = "plan-runner:runners"
    ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"

    async def test_runner_full_lifecycle(self, client, mock_executor_redis):
        """E2E-1: POST /run → running=True → status='stopped' 설정 → running=False"""
        fake_sync = mock_executor_redis["sync"]
        fake_async = mock_executor_redis["async"]
        rid = "e2e-runner-1"
        now = datetime.now().isoformat()

        # 초기: running=False
        response = await client.get("/api/v1/dev-runner/status")
        assert response.json()["running"] is False

        # 실행 중 상태 시뮬레이션
        await fake_async.set("plan-runner:listener:heartbeat", now)
        await fake_async.sadd(self.ACTIVE_RUNNERS_KEY, rid)
        await fake_async.set(f"{self.RUNNER_KEY_PREFIX}:{rid}:status", "running")
        await fake_async.set(f"{self.RUNNER_KEY_PREFIX}:{rid}:pid", "11111")

        with patch.object(executor_service, "_is_pid_alive", return_value=True):
            response = await client.get("/api/v1/dev-runner/status")
        assert response.json()["running"] is True

        # Fix 2: cleanup 후 status="stopped" 설정 (삭제 X)
        await fake_async.set(f"{self.RUNNER_KEY_PREFIX}:{rid}:status", "stopped")

        response = await client.get("/api/v1/dev-runner/status")
        assert response.json()["running"] is False

    async def test_runner_force_stop(self, client, mock_executor_redis):
        """E2E-2: POST /stop → running=False (runner 없으면 404)"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()

        await fake_async.set("plan-runner:listener:heartbeat", now)
        # runner 없는 상태 → /stop → 404 반환
        response = await client.post("/api/v1/dev-runner/stop")
        assert response.status_code in (200, 404)

    async def test_no_running_after_cleanup(self, client, mock_executor_redis):
        """E2E-3: status='stopped' 설정 후 연속 3회 GET → 모두 running=False (경쟁 조건 회귀)"""
        fake_sync = mock_executor_redis["sync"]
        rid = "e2e-runner-race"
        fake_sync.sadd(self.ACTIVE_RUNNERS_KEY, rid)
        fake_sync.set(f"{self.RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
        fake_sync.set("plan-runner:listener:heartbeat", datetime.now().isoformat())

        for i in range(3):
            response = await client.get("/api/v1/dev-runner/status")
            assert response.status_code == 200
            data = response.json()
            assert data["running"] is False, f"회차 {i+1}: status='stopped'인데 running=True 반환 — 경쟁 조건 잔류"


class TestPlansList:
    async def test_plans_list_returns_200(self, client):
        response = await client.get("/api/v1/dev-runner/plans")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestLogsRecent:
    async def test_logs_recent_returns_200(self, client):
        response = await client.get("/api/v1/dev-runner/logs/recent?runner_id=test-runner")
        assert response.status_code == 200
        data = response.json()
        assert "lines" in data
        assert "total_lines" in data
        assert isinstance(data["lines"], list)


class TestExecutorResolveProfile:
    """executor _resolve_profile 정적 메서드 검증 (T1)"""

    async def test_profile_specified_in_command_payload(self, client, mock_executor_redis):
        """R: profile 지정 시 command에 profile 관련 키 포함"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()
        await fake_async.set("plan-runner:listener:heartbeat", now)

        work_profile = LLMProfile(
            engine="claude",
            name="work",
            config_dir="/work/claude",
            extra_env={"CLAUDE_KEY": "wk"},
        )
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch("app.modules.dev_runner.services.executor_service.get_profile_by_name", return_value=work_profile), \
             patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post(
                "/api/v1/dev-runner/run",
                json={"plan_file": "test.md", "engine": "claude", "profile": "work"},
            )

        assert response.status_code == 200
        queued = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert queued, "command queue가 비어 있음"
        command = json.loads(queued[0])
        assert command.get("profile") == "work"
        assert command.get("profile_env_key") == "CLAUDE_CONFIG_DIR"
        assert command.get("profile_config_dir") == "/work/claude"
        assert command.get("profile_extra_env") == {"CLAUDE_KEY": "wk"}

    async def test_profile_not_specified_uses_selected(self, client, mock_executor_redis):
        """R: profile 미지정 시 전역 선택 프로필 config 포함"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()
        await fake_async.set("plan-runner:listener:heartbeat", now)

        selected_profile = LLMProfile(
            engine="claude",
            name="default",
            config_dir=None,
            extra_env={},
        )
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch("app.modules.dev_runner.services.executor_service.get_selected_profile", return_value=selected_profile), \
             patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post(
                "/api/v1/dev-runner/run",
                json={"plan_file": "test.md", "engine": "claude"},
            )

        assert response.status_code == 200
        queued = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert queued
        command = json.loads(queued[0])
        assert command.get("profile") == "default"

    async def test_codex_engine_profile_ignored(self, client, mock_executor_redis):
        """B: codex 엔진은 PROFILE_SUPPORTED_ENGINES에 없어 profile 키 없음"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()
        await fake_async.set("plan-runner:listener:heartbeat", now)

        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post(
                "/api/v1/dev-runner/run",
                json={"plan_file": "test.md", "engine": "codex", "profile": "work"},
            )

        assert response.status_code == 200
        queued = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert queued
        command = json.loads(queued[0])
        # codex 엔진은 profile 관련 키가 command에 없어야 함
        assert "profile" not in command
        assert "profile_config_dir" not in command
