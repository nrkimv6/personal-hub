"""실행 제어 API 테스트 - fakeredis + patch.object 적용"""

import json
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime
from types import SimpleNamespace

import pytest
import redis
import fakeredis
import fakeredis.aioredis
from pydantic import ValidationError

from app.modules.claude_worker.services.profile_store import LLMProfile
from app.modules.dev_runner.schemas import RunRequest
from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.services.state import get_state

RESULTS_KEY = "plan-runner:command_results"


@pytest.fixture(autouse=True)
def mock_executor_redis():
    """executor_service의 async_redis와 redis_client를 fakeredis로 교체"""
    fake_sync = fakeredis.FakeRedis(decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mock_claim = MagicMock()
    mock_claim.claim_id = "test-claim-id"
    with patch.object(executor_service, 'redis_client', fake_sync), \
         patch.object(executor_service, 'async_redis', fake_async), \
         patch('app.modules.dev_runner.services.plan_execution_claim_service.claim_plan', return_value=mock_claim):
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

    async def test_double_start_returns_429(self, client, mock_executor_redis):
        """max_concurrent_runners 초과 시 429 반환 — 동시 실행 제한 short-circuit 검증"""
        from app.modules.dev_runner.services.executor_service import ACTIVE_RUNNERS_KEY, RUNNER_KEY_PREFIX
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())
        mocked_settings = SimpleNamespace(
            max_concurrent_runners=3,
            default_engine="claude",
            default_fix_engine="claude",
        )
        # 설정 파일 값과 무관하게 over-limit 분기를 강제 재현한다.
        for i in range(3):
            rid = f"existing-runner-{i}"
            await fake_async.sadd(ACTIVE_RUNNERS_KEY, rid)
            await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
            await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", str(10000 + i))

        with patch.object(executor_service, '_is_pid_alive', return_value=True), \
             patch.object(fake_async, 'brpop', new=AsyncMock(return_value=None)) as mock_brpop, \
             patch("app.modules.dev_runner.services.executor_service.settings_service.get", return_value=mocked_settings):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md"
            })
        assert response.status_code == 429
        mock_brpop.assert_not_awaited()

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

    async def test_start_reserved_status_returns_409_not_timeout(self, client, mock_executor_redis):
        """예약대기 blocked listener 결과는 listener timeout/500이 아니라 409로 노출한다."""
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())
        brpop_result = (
            "plan-runner:command_results:abc123",
            json.dumps({
                "success": False,
                "reason": "reserved_status",
                "status": "예약대기",
                "message": "예약대기 plan은 실행할 수 없습니다: reserved.md",
            }, ensure_ascii=False),
        )

        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "reserved.md"
            })

        assert response.status_code == 409
        assert "예약대기" in response.json()["detail"]

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

    async def test_start_run_uses_settings_default_engines_when_request_missing(self, client, mock_executor_redis):
        """요청에 engine/fix_engine 미지정 시 settings 기본값 사용"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()

        await fake_async.set("plan-runner:listener:heartbeat", now)
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        mocked_settings = SimpleNamespace(
            max_concurrent_runners=3,
            default_engine="gemini",
            default_fix_engine="codex",
        )

        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)), \
             patch("app.modules.dev_runner.services.executor_service.settings_service.get", return_value=mocked_settings):
            response = await client.post("/api/v1/dev-runner/run", json={"plan_file": "test-plan.md"})

        assert response.status_code == 200
        raw = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert len(raw) > 0, "command queue에 항목 없음"
        command = json.loads(raw[0])
        assert command.get("engine") == "gemini"
        assert command.get("fix_engine") == "codex"

    async def test_start_run_engine_cc_codex_stored_in_command(self, client, mock_executor_redis):
        """cc-codex main engine 필드가 Redis command에 포함되는지 확인"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()

        await fake_async.set("plan-runner:listener:heartbeat", now)
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, 'brpop', new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "engine": "cc-codex",
            })

        assert response.status_code == 200
        raw = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert len(raw) > 0, "command queue에 항목 없음"
        command = json.loads(raw[0])
        assert command.get("engine") == "cc-codex", f"engine 미포함: {command}"

    async def test_start_run_fix_engine_cc_codex_stored_in_command(self, client, mock_executor_redis):
        """cc-codex fix_engine 필드가 Redis command에 포함되는지 확인"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()

        await fake_async.set("plan-runner:listener:heartbeat", now)
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, 'brpop', new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "fix_engine": "cc-codex",
            })

        assert response.status_code == 200
        raw = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert len(raw) > 0, "command queue에 항목 없음"
        command = json.loads(raw[0])
        assert command.get("fix_engine") == "cc-codex", f"fix_engine 미포함: {command}"

    async def test_start_run_engine_codex_stored_in_command(self, client, mock_executor_redis):
        """codex main engine 필드가 Redis command에 포함되는지 확인"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()

        await fake_async.set("plan-runner:listener:heartbeat", now)
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, 'brpop', new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "engine": "codex",
            })

        assert response.status_code == 200
        raw = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert len(raw) > 0, "command queue에 항목 없음"
        command = json.loads(raw[0])
        assert command.get("engine") == "codex", f"engine 미포함: {command}"

    async def test_start_run_fix_engine_codex_stored_in_command(self, client, mock_executor_redis):
        """codex fix_engine 필드가 Redis command에 포함되는지 확인"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()

        await fake_async.set("plan-runner:listener:heartbeat", now)
        brpop_result = ("plan-runner:command_results:abc123", json.dumps({"success": True, "message": "Started"}))
        with patch.object(fake_async, 'brpop', new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "fix_engine": "codex",
            })

        assert response.status_code == 200
        raw = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert len(raw) > 0, "command queue에 항목 없음"
        command = json.loads(raw[0])
        assert command.get("fix_engine") == "codex", f"fix_engine 미포함: {command}"

    async def test_start_run_unknown_engine_returns_422(self, client, mock_executor_redis):
        """알 수 없는 engine 요청은 5xx가 아닌 422로 명시 실패"""
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())

        response = await client.post("/api/v1/dev-runner/run", json={
            "plan_file": "test-plan.md",
            "engine": "unknown-engine",
        })

        assert response.status_code == 422
        assert "지원되지 않는 엔진" in response.text

    async def test_start_run_codex_preflight_failure_returns_422(self, client, mock_executor_redis):
        """codex preflight 실패는 5xx가 아닌 422로 반환"""
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())

        brpop_result = (
            "plan-runner:command_results:abc123",
            json.dumps({"success": False, "message": "codex 인증 실패: CLI 로그인/토큰 상태를 확인하세요."}),
        )
        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "engine": "codex",
            })

        assert response.status_code == 422
        assert "codex 인증 실패" in response.text

    async def test_start_run_codex_runtime_failure_not_preflight_422(self, client, mock_executor_redis):
        """codex 요청이 accepted된 경우 runtime 실패는 start 단계 preflight 422 대상이 아님"""
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())

        brpop_result = (
            "plan-runner:command_results:abc123",
            json.dumps({"success": True, "message": "Started"}),
        )
        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "engine": "codex",
                "fix_engine": "codex",
            })

        assert response.status_code == 200
        assert response.json()["running"] is True

    async def test_start_run_codex_runtime_failure_marker_detected_in_message(self, client, mock_executor_redis):
        """model_reasoning_effort/xhigh 문자열은 preflight(422)가 아닌 runtime 실패(500)로 분류"""
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())

        brpop_result = (
            "plan-runner:command_results:abc123",
            json.dumps(
                {
                    "success": False,
                    "message": "Error: unknown variant `xhigh`, expected one of `minimal`, `low`, `medium`, `high`\nin `model_reasoning_effort`",
                }
            ),
        )
        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "engine": "codex",
                "fix_engine": "codex",
            })

        assert response.status_code == 500
        assert "model_reasoning_effort" in response.text

    async def test_start_run_non_codex_failure_keeps_500(self, client, mock_executor_redis):
        """codex와 무관한 listener 실패는 기존대로 500 유지"""
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())

        brpop_result = (
            "plan-runner:command_results:abc123",
            json.dumps({"success": False, "message": "Already running (PID: 12345)"}),
        )
        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=brpop_result)):
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "engine": "claude",
            })

        assert response.status_code == 500
        assert "Already running" in response.text


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


class TestRunRequestProfileField:
    """RunRequest profile 필드 TC (T1)"""

    def test_profile_field_right_valid(self):
        """R: profile 필드 정상 지정"""
        req = RunRequest(plan_file="test.md", engine="claude", profile="work")
        assert req.profile == "work"

    def test_profile_field_none_default(self):
        """R: profile 미지정 시 None"""
        req = RunRequest(plan_file="test.md", engine="claude")
        assert req.profile is None

    def test_profile_field_empty_string_normalized_to_none(self):
        """B: profile="" 빈 문자열 → None으로 정규화"""
        req = RunRequest(plan_file="test.md", engine="claude", profile="")
        assert req.profile is None

    def test_profile_field_whitespace_normalized_to_none(self):
        """B: profile="  " 공백 문자열 → None으로 정규화"""
        req = RunRequest(plan_file="test.md", engine="claude", profile="  ")
        assert req.profile is None

    def test_profile_field_non_string_raises(self):
        """E: profile에 비문자열(int) 전달 → ValidationError"""
        with pytest.raises((ValidationError, Exception)):
            req = RunRequest(plan_file="test.md", engine="claude", profile=123)
            # Pydantic v2는 str coerce할 수 있어 명시 확인
            assert isinstance(req.profile, (str, type(None)))

    async def test_run_request_profile_right_returns_200(self, client, mock_executor_redis):
        """R: POST /run with profile → 200 + command에 profile_config_dir 포함"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()
        await fake_async.set("plan-runner:listener:heartbeat", now)

        work_profile = LLMProfile(
            engine="claude",
            name="work",
            config_dir="/test/path",
            extra_env={"TEST_KEY": "val"},
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
        assert queued
        command = json.loads(queued[0])
        assert command.get("profile_config_dir") == "/test/path"
        assert command.get("profile_extra_env") == {"TEST_KEY": "val"}
        assert command.get("profile_env_key") == "CLAUDE_CONFIG_DIR"

    async def test_run_request_nonexistent_profile_returns_400(self, client, mock_executor_redis):
        """E: 존재하지 않는 profile → 400 에러"""
        fake_async = mock_executor_redis["async"]
        now = datetime.now().isoformat()
        await fake_async.set("plan-runner:listener:heartbeat", now)

        with patch(
            "app.modules.dev_runner.services.executor_service.get_profile_by_name",
            side_effect=ValueError("profile 'nonexistent' not found for engine 'claude'"),
        ):
            response = await client.post(
                "/api/v1/dev-runner/run",
                json={"plan_file": "test.md", "engine": "claude", "profile": "nonexistent"},
            )

        assert response.status_code == 400
        assert "not found" in response.json().get("detail", "")

    async def test_run_request_codex_engine_profile_ignored(self, client, mock_executor_redis):
        """B: codex 엔진 + profile 지정 → 200 + profile 관련 키 없음"""
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
        # codex 엔진은 프로필 미지원 → profile 관련 키 없음
        assert "profile" not in command
        assert "profile_config_dir" not in command
        assert "profile_extra_env" not in command


class TestListRunners:
    """GET /runners — Redis 장애 계약 및 정상 응답 고정"""

    async def test_list_runners_redis_down_503(self, client, mock_executor_redis):
        """E: Redis ConnectionError → 503 + detail='Redis 연결 실패' (readiness 분리 고정)"""
        with patch.object(
            executor_service,
            "get_all_runners",
            new=AsyncMock(side_effect=redis.ConnectionError("test")),
        ):
            response = await client.get("/api/v1/dev-runner/runners")
        assert response.status_code == 503
        assert response.json().get("detail") == "Redis 연결 실패"

    async def test_list_runners_empty_when_no_active(self, client, mock_executor_redis):
        """B: fakeredis 정상 상태, active runner 없음 → 200 + 빈 리스트 []"""
        response = await client.get("/api/v1/dev-runner/runners")
        assert response.status_code == 200
        assert response.json() == []


class TestMergeApprovalPayload:
    async def test_merge_retry_request_forwards_approve_service_lock(self, client):
        """R: POST /merge/{runner_id}/retry with approve_service_lock=true → command payload 포함"""
        rid = "merge-retry-001"
        mocked = AsyncMock(return_value={"success": True, "message": "ok"})
        with patch.object(executor_service, "_send_command", new=mocked):
            response = await client.post(
                f"/api/v1/dev-runner/merge/{rid}/retry",
                json={
                    "worktree_path": "D:/work/project/tools/monitor-page/.worktrees/impl-x",
                    "plan_file": "docs/plan/test.md",
                    "branch": "impl/test",
                    "approve_service_lock": True,
                },
            )
        assert response.status_code == 200
        sent = mocked.call_args.args[0]
        assert sent.get("action") == "retry-merge"
        assert sent.get("runner_id") == rid
        assert sent.get("approve_service_lock") is True
        assert sent.get("worktree_path")
        assert sent.get("plan_file")
        assert sent.get("branch")

    async def test_legacy_runner_retry_merge_forwards_approve_service_lock(self, client):
        """B: POST /runners/{runner_id}/retry-merge도 approve_service_lock payload를 전달한다."""
        rid = "merge-retry-legacy-001"
        mocked = AsyncMock(return_value={"success": True, "message": "ok"})
        with patch.object(executor_service, "_send_command", new=mocked):
            response = await client.post(
                f"/api/v1/dev-runner/runners/{rid}/retry-merge",
                json={"approve_service_lock": True},
            )
        assert response.status_code == 200
        sent = mocked.call_args.args[0]
        assert sent.get("action") == "retry-merge"
        assert sent.get("runner_id") == rid
        assert sent.get("approve_service_lock") is True

    async def test_direct_merge_request_forwards_approve_service_lock(self, client):
        """R: POST /merge/direct with approve_service_lock=true → command payload 포함"""
        mocked = AsyncMock(return_value={"success": True, "message": "ok"})
        with patch.object(executor_service, "_send_command", new=mocked):
            response = await client.post(
                "/api/v1/dev-runner/merge/direct",
                json={
                    "branch": "impl/test",
                    "worktree_path": "D:/work/project/tools/monitor-page/.worktrees/impl-test",
                    "plan_file": "docs/plan/test.md",
                    "approve_service_lock": True,
                },
            )
        assert response.status_code == 200
        sent = mocked.call_args.args[0]
        assert sent.get("action") == "direct-merge"
        assert sent.get("approve_service_lock") is True

    async def test_get_merge_status_returns_reason_and_message_for_approval_required(self, client, mock_executor_redis):
        """T5-R: GET /merge/{runner_id}는 approval_required + reason/message를 반환한다."""
        fake_async = mock_executor_redis["async"]
        rid = "merge-status-approval-001"
        prefix = f"plan-runner:runners:{rid}"
        await fake_async.set(f"{prefix}:merge_status", "approval_required")
        await fake_async.set(f"{prefix}:merge_reason", "service_lock")
        await fake_async.set(f"{prefix}:merge_message", "MERGE_PRECHECK_FAILED[service_lock]: blocked")

        response = await client.get(f"/api/v1/dev-runner/merge/{rid}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approval_required"
        assert data["reason"] == "service_lock"
        assert "MERGE_PRECHECK_FAILED[service_lock]" in data["message"]
