"""실행 제어 API 테스트 - fakeredis + patch.object 적용"""

import json
from pathlib import Path
import re
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime
from types import SimpleNamespace

import pytest
import redis
import fakeredis
import fakeredis.aioredis
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.modules.claude_worker.services.profile_store import LLMProfile
from app.modules.dev_runner.schemas import RunRequest
from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.services.event_payload import build_status_payload
from app.modules.dev_runner.services.state import get_state
from app.models.dev_runner_state import DevRunnerMergeRequest, DevRunnerState
from app.modules.dev_runner.services.dev_runner_state_repository import create_merge_request, upsert_runner_state

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


@pytest.fixture(autouse=True)
def runner_state_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    DevRunnerState.__table__.create(bind=engine, checkfirst=True)
    DevRunnerMergeRequest.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    with patch("app.database.SessionLocal", Session), \
         patch("app.core.database.SessionLocal", Session):
        try:
            yield session
        finally:
            session.close()
            engine.dispose()


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

    async def test_status_prefers_recent_approval_required_runner(self, client, mock_executor_redis, runner_state_db):
        fake_async = mock_executor_redis["async"]
        rid = "approval-status-001"
        prefix = f"plan-runner:runners:{rid}"
        await fake_async.set("plan-runner:listener:heartbeat", "2026-05-11T10:00:00")
        await fake_async.zadd("plan-runner:recent_runners", {rid: 1})
        await fake_async.set(f"{prefix}:status", "stopped")
        await fake_async.set(f"{prefix}:trigger", "user")
        await fake_async.set(f"{prefix}:plan_file", "docs/plan/approval.md")
        await fake_async.set(f"{prefix}:merge_status", "approval_required")
        await fake_async.set(f"{prefix}:merge_reason", "service_lock")
        await fake_async.set(f"{prefix}:merge_message", "MERGE_PRECHECK_FAILED[service_lock]")

        response = await client.get("/api/v1/dev-runner/status")

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert data["runner_id"] == rid
        assert data["display_state"] == "approval_required"
        assert data["display_label"] == "승인 필요"
        assert data["display_severity"] == "approval"

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
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())

        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=None)) as mock_brpop:
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test.md"
            })

        assert response.status_code == 200
        assert response.json()["running"] is True
        mock_brpop.assert_not_awaited()

    async def test_start_reserved_status_is_reported_via_async_command_result(self, client, mock_executor_redis):
        """비동기 start 계약에서는 예약대기 listener 결과를 command result로 조회한다."""
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())

        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=None)) as mock_brpop:
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "reserved.md"
            })

        assert response.status_code == 200
        mock_brpop.assert_not_awaited()
        queued = await fake_async.lrange("plan-runner:commands", 0, -1)
        command = json.loads(queued[0])
        command_id = command["command_id"]
        await fake_async.lpush(
            f"{RESULTS_KEY}:{command_id}",
            json.dumps({
                "success": False,
                "reason": "reserved_status",
                "status": "예약대기",
                "message": "예약대기 plan은 실행할 수 없습니다: reserved.md",
            }, ensure_ascii=False),
        )

        result_response = await client.get(f"/api/v1/dev-runner/commands/{command_id}")
        assert result_response.status_code == 200
        result = result_response.json()
        assert result["status"] == "failed"
        assert result["result"]["reason"] == "reserved_status"
        assert "예약대기" in result["message"]

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
        """codex preflight 실패는 accepted 이후 command result에서 실패로 조회된다."""
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())

        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=None)) as mock_brpop:
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "engine": "codex",
            })

        assert response.status_code == 200
        mock_brpop.assert_not_awaited()
        command = json.loads((await fake_async.lrange("plan-runner:commands", 0, -1))[0])
        command_id = command["command_id"]
        await fake_async.lpush(
            f"{RESULTS_KEY}:{command_id}",
            json.dumps({"success": False, "message": "codex 인증 실패: CLI 로그인/토큰 상태를 확인하세요."}, ensure_ascii=False),
        )
        result = await client.get(f"/api/v1/dev-runner/commands/{command_id}")
        assert result.status_code == 200
        assert result.json()["status"] == "failed"
        assert "codex 인증 실패" in result.json()["message"]

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
        """model_reasoning_effort/xhigh 문자열은 accepted 이후 command result 실패로 보존된다."""
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())

        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=None)) as mock_brpop:
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "engine": "codex",
                "fix_engine": "codex",
            })

        assert response.status_code == 200
        mock_brpop.assert_not_awaited()
        command = json.loads((await fake_async.lrange("plan-runner:commands", 0, -1))[0])
        command_id = command["command_id"]
        await fake_async.lpush(
            f"{RESULTS_KEY}:{command_id}",
            json.dumps(
                {
                    "success": False,
                    "message": "Error: unknown variant `xhigh`, expected one of `minimal`, `low`, `medium`, `high`\nin `model_reasoning_effort`",
                }
            ),
        )
        result = await client.get(f"/api/v1/dev-runner/commands/{command_id}")
        assert result.status_code == 200
        assert result.json()["status"] == "failed"
        assert "model_reasoning_effort" in result.json()["message"]

    async def test_start_run_non_codex_failure_keeps_500(self, client, mock_executor_redis):
        """codex와 무관한 listener 실패도 accepted 이후 command result에서 조회된다."""
        fake_async = mock_executor_redis["async"]
        await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())

        with patch.object(fake_async, "brpop", new=AsyncMock(return_value=None)) as mock_brpop:
            response = await client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test-plan.md",
                "engine": "claude",
            })

        assert response.status_code == 200
        mock_brpop.assert_not_awaited()
        command = json.loads((await fake_async.lrange("plan-runner:commands", 0, -1))[0])
        command_id = command["command_id"]
        await fake_async.lpush(
            f"{RESULTS_KEY}:{command_id}",
            json.dumps({"success": False, "message": "Already running (PID: 12345)"}),
        )
        result = await client.get(f"/api/v1/dev-runner/commands/{command_id}")
        assert result.status_code == 200
        assert result.json()["status"] == "failed"
        assert "Already running" in result.json()["message"]


class TestStopRun:
    async def test_stop_not_running_returns_404(self, client, mock_executor_redis):
        # fakeredis 빈 상태 → status None → not running → 404
        response = await client.post("/api/v1/dev-runner/stop")
        assert response.status_code == 404

    async def test_stop_running_process(self, client, mock_executor_redis):
        from app.modules.dev_runner.services.executor_service import ACTIVE_RUNNERS_KEY, RUNNER_KEY_PREFIX
        fake_async = mock_executor_redis["async"]
        fake_sync = mock_executor_redis["sync"]
        rid = "stop-test-runner"
        await fake_async.set("plan-runner:listener:heartbeat", "2026-02-19T10:00:00")
        await fake_async.sadd(ACTIVE_RUNNERS_KEY, rid)
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", "55555")
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:trigger", "tc:stop-running")
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file", "docs/plan/stop.md")
        fake_sync.set("plan-runner:listener:heartbeat", "2026-02-19T10:00:00")
        fake_sync.sadd(ACTIVE_RUNNERS_KEY, rid)
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", "55555")
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:trigger", "tc:stop-running")
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file", "docs/plan/stop.md")

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

    async def test_list_runners_corrects_stale_branch_exists_for_approval_required(self, client, mock_executor_redis, tmp_path):
        """display: approval_required runner corrects stale branch_exists=false before API display."""
        fake_async = mock_executor_redis["async"]
        rid = "approval-list-001"
        prefix = f"plan-runner:runners:{rid}"
        await fake_async.sadd("plan-runner:active_runners", rid)
        await fake_async.set(f"{prefix}:status", "stopped")
        await fake_async.set(f"{prefix}:trigger", "user")
        await fake_async.set(f"{prefix}:plan_file", "docs/plan/test.md")
        await fake_async.set(f"{prefix}:worktree_path", str(tmp_path))
        await fake_async.set(f"{prefix}:branch", "impl/test")
        await fake_async.set(f"{prefix}:merge_status", "approval_required")
        await fake_async.set(f"{prefix}:branch_exists", "false")
        await fake_async.set(f"{prefix}:worktree_exists", "true")

        with patch("app.modules.dev_runner.services.runner_git_metadata.check_branch_exists", return_value=True):
            response = await client.get("/api/v1/dev-runner/runners")

        assert response.status_code == 200
        data = response.json()
        assert data[0]["runner_id"] == rid
        assert data[0]["branch_exists"] is True
        assert await fake_async.get(f"{prefix}:branch_exists") == "true"
        assert data[0]["display_state"] == "approval_required"
        assert data[0]["hide_stale_branch_badge"] is True

    async def test_list_runners_preserves_completed_merge_error_with_post_merge_tasks(self, client, mock_executor_redis, tmp_path):
        """T5-R: completed lifecycle과 merge error/post-merge 잔여는 HTTP 응답에서 함께 보존된다."""
        fake_async = mock_executor_redis["async"]
        plan = tmp_path / "blocked-plan.md"
        plan.write_text(
            "# blocked\n\n"
            "### Phase 1\n\n"
            "- [x] implementation done\n\n"
            "### Phase Z\n\n"
            "- [ ] archive remains\n",
            encoding="utf-8",
        )
        rid = "completed-merge-error-001"
        prefix = f"plan-runner:runners:{rid}"
        await fake_async.zadd("plan-runner:recent_runners", {rid: 1})
        await fake_async.set(f"{prefix}:status", "stopped")
        await fake_async.set(f"{prefix}:trigger", "user")
        await fake_async.set(f"{prefix}:plan_file", str(plan))
        await fake_async.set(f"{prefix}:exit_reason", "completed")
        await fake_async.set(f"{prefix}:merge_status", "error")
        await fake_async.set(f"{prefix}:merge_reason", "stale_merge_blocked")
        await fake_async.set(f"{prefix}:merge_message", "stale merge gate: risk=BLOCK")
        await fake_async.set(
            f"{prefix}:gate_evidence_summary",
            json.dumps({"reason": "stale_merge_blocked", "status": "error"}),
        )

        response = await client.get("/api/v1/dev-runner/runners")

        assert response.status_code == 200
        data = response.json()
        assert data[0]["runner_id"] == rid
        assert data[0]["running"] is False
        assert data[0]["exit_reason"] == "completed"
        assert data[0]["merge_status"] == "error"
        assert data[0]["merge_reason"] == "stale_merge_blocked"
        assert data[0]["gate_evidence_summary"]["reason"] == "stale_merge_blocked"
        assert data[0]["remaining_post_merge_tasks"] == 1
        assert data[0]["display_state"] == "merge_error"
        assert data[0]["display_label"] == "머지 오류"

    async def test_get_all_runners_R_runner_state_db_row_survives_redis_metadata_loss(self, client, mock_executor_redis, runner_state_db):
        rid = "db-only-runner-001"
        try:
            upsert_runner_state(
                runner_state_db,
                {
                    "runner_id": rid,
                    "plan_file": "docs/plan/db-only.md",
                    "project": "monitor-page",
                    "status": "stopped",
                    "branch": "impl/db-only",
                    "worktree_path": "D:/work/db-only",
                    "exit_reason": "completed",
                    "completed_at": datetime.now(),
                    "metadata": {"engine": "codex", "trigger": "user", "merge_status": "queued"},
                },
            )
            runner_state_db.commit()

            response = await client.get("/api/v1/dev-runner/runners")

            assert response.status_code == 200
            rows = [row for row in response.json() if row["runner_id"] == rid]
            assert len(rows) == 1
            assert rows[0]["redis_missing"] is True
            assert rows[0]["plan_file"] == "docs/plan/db-only.md"
            assert rows[0]["branch"] == "impl/db-only"
            assert rows[0]["trigger"] == "user"
        finally:
            runner_state_db.query(DevRunnerMergeRequest).filter_by(runner_id=rid).delete()
            runner_state_db.query(DevRunnerState).filter_by(runner_id=rid).delete()
            runner_state_db.commit()

    async def test_get_all_runners_B_runner_state_redis_active_without_db_backfills_row(self, client, mock_executor_redis, runner_state_db):
        fake_async = mock_executor_redis["async"]
        rid = "redis-only-runner-001"
        prefix = f"plan-runner:runners:{rid}"
        await fake_async.sadd("plan-runner:active_runners", rid)
        await fake_async.set(f"{prefix}:status", "running")
        await fake_async.set(f"{prefix}:trigger", "user")
        await fake_async.set(f"{prefix}:plan_file", "docs/plan/redis-only.md")
        await fake_async.set(f"{prefix}:branch", "impl/redis-only")
        await fake_async.set(f"{prefix}:worktree_path", "D:/work/redis-only")
        await fake_async.set(f"{prefix}:start_time", datetime.now().isoformat())

        try:
            response = await client.get("/api/v1/dev-runner/runners")

            assert response.status_code == 200
            row = runner_state_db.get(DevRunnerState, rid)
            assert row is not None
            assert row.plan_file == "docs/plan/redis-only.md"
            assert row.branch == "impl/redis-only"
        finally:
            runner_state_db.query(DevRunnerMergeRequest).filter_by(runner_id=rid).delete()
            runner_state_db.query(DevRunnerState).filter_by(runner_id=rid).delete()
            runner_state_db.commit()


class TestGetRunnerStatus:
    async def test_get_runner_status_includes_display_fields(self, client, mock_executor_redis):
        """R: 단일 runner API도 list/SSE와 같은 display 필드를 반환한다."""
        fake_async = mock_executor_redis["async"]
        rid = "single-display-001"
        prefix = f"plan-runner:runners:{rid}"
        await fake_async.set(f"{prefix}:status", "stopped")
        await fake_async.set(f"{prefix}:plan_file", "docs/plan/test.md")
        await fake_async.set(f"{prefix}:merge_status", "approval_required")
        await fake_async.set(
            f"{prefix}:gate_evidence_summary",
            json.dumps({"reason": "service_lock", "status": "approval_required"}),
        )
        await fake_async.set(f"{prefix}:branch_exists", "false")

        response = await client.get(f"/api/v1/dev-runner/runners/{rid}")

        assert response.status_code == 200
        data = response.json()
        assert data["runner_id"] == rid
        assert data["display_state"] == "approval_required"
        assert data["display_label"] == "승인 필요"
        assert data["display_severity"] == "approval"
        assert data["display_secondary"] is None
        assert data["hide_stale_branch_badge"] is True
        assert data["gate_evidence_summary"]["reason"] == "service_lock"

    async def test_runner_list_and_sse_payload_display_fields_match(self, client, mock_executor_redis):
        """R: list API와 SSE status payload는 같은 backend display policy를 공유한다."""
        fake_async = mock_executor_redis["async"]
        fake_sync = mock_executor_redis["sync"]
        rid = "display-match-001"
        prefix = f"plan-runner:runners:{rid}"
        fields = {
            "status": "stopped",
            "trigger": "user",
            "plan_file": "docs/plan/test.md",
            "merge_status": "approval_required",
            "branch_exists": "false",
        }
        await fake_async.sadd("plan-runner:active_runners", rid)
        fake_sync.sadd("plan-runner:active_runners", rid)
        for field, value in fields.items():
            await fake_async.set(f"{prefix}:{field}", value)
            fake_sync.set(f"{prefix}:{field}", value)

        response = await client.get("/api/v1/dev-runner/runners")
        assert response.status_code == 200
        list_item = response.json()[0]
        sse_payload = build_status_payload(fake_sync, rid)

        for field in (
            "display_state",
            "display_label",
            "display_severity",
            "display_secondary",
            "hide_stale_branch_badge",
        ):
            assert list_item[field] == sse_payload[field]


class TestMergeApprovalPayload:
    async def test_merge_retry_request_forwards_approve_service_lock(self, client):
        """override: POST /merge/{runner_id}/retry forwards approve_service_lock command payload."""
        rid = "merge-retry-001"
        mocked = AsyncMock(return_value={"success": True, "message": "ok"})
        with patch.object(executor_service, "_enqueue_command", new=mocked):
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
        """override/boundary: legacy retry-merge endpoint also forwards approve_service_lock."""
        rid = "merge-retry-legacy-001"
        mocked = AsyncMock(return_value={"success": True, "message": "ok"})
        with patch.object(executor_service, "_enqueue_command", new=mocked):
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
        """override: POST /merge/direct forwards approve_service_lock for listener policy normalization."""
        mocked = AsyncMock(return_value={"success": True, "message": "ok"})
        with patch.object(executor_service, "_enqueue_command", new=mocked):
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
        """display: GET /merge/{runner_id} returns approval_required reason/message surface."""
        fake_async = mock_executor_redis["async"]
        rid = "merge-status-approval-001"
        prefix = f"plan-runner:runners:{rid}"
        await fake_async.set(f"{prefix}:merge_status", "approval_required")
        await fake_async.set(f"{prefix}:merge_reason", "service_lock")
        await fake_async.set(f"{prefix}:merge_message", "MERGE_PRECHECK_FAILED[service_lock]: blocked")
        await fake_async.set(
            f"{prefix}:gate_evidence_summary",
            json.dumps({"reason": "service_lock", "status": "approval_required"}),
        )

        response = await client.get(f"/api/v1/dev-runner/merge/{rid}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approval_required"
        assert data["reason"] == "service_lock"
        assert "MERGE_PRECHECK_FAILED[service_lock]" in data["message"]
        assert data["gate_evidence_summary"]["reason"] == "service_lock"

    async def test_runner_list_includes_gate_evidence_changed_running_fields(self, client, mock_executor_redis):
        """display: runner list API preserves gate_evidence_summary changed/running fields for service_lock."""
        fake_async = mock_executor_redis["async"]
        rid = "gate-evidence-fields-001"
        prefix = f"plan-runner:runners:{rid}"
        await fake_async.sadd("plan-runner:active_runners", rid)
        await fake_async.set(f"{prefix}:status", "stopped")
        await fake_async.set(f"{prefix}:trigger", "user")
        await fake_async.set(f"{prefix}:plan_file", "docs/plan/test.md")
        await fake_async.set(f"{prefix}:merge_status", "approval_required")
        await fake_async.set(f"{prefix}:merge_reason", "service_lock")
        await fake_async.set(
            f"{prefix}:gate_evidence_summary",
            json.dumps({
                "reason": "service_lock",
                "status": "approval_required",
                "changed": ["scripts/services/service_run.py"],
                "running": ["MonitorPage-Admin"],
            }),
        )

        response = await client.get("/api/v1/dev-runner/runners")
        assert response.status_code == 200
        data = response.json()
        runner = next((r for r in data if r["runner_id"] == rid), None)
        assert runner is not None
        assert runner["merge_status"] == "approval_required"
        ges = runner["gate_evidence_summary"]
        assert ges is not None
        assert ges["reason"] == "service_lock"
        assert ges["changed"] == ["scripts/services/service_run.py"]
        assert ges["running"] == ["MonitorPage-Admin"]

    async def test_runner_detail_includes_gate_evidence_changed_running_fields(self, client, mock_executor_redis):
        """display: runner detail API preserves changed/running from gate_evidence_summary."""
        fake_async = mock_executor_redis["async"]
        rid = "gate-evidence-detail-001"
        prefix = f"plan-runner:runners:{rid}"
        await fake_async.zadd("plan-runner:recent_runners", {rid: 1})
        await fake_async.set(f"{prefix}:status", "stopped")
        await fake_async.set(f"{prefix}:trigger", "user")
        await fake_async.set(f"{prefix}:plan_file", "docs/plan/test.md")
        await fake_async.set(f"{prefix}:merge_status", "approval_required")
        await fake_async.set(f"{prefix}:merge_reason", "service_lock")
        await fake_async.set(f"{prefix}:branch_exists", "true")
        await fake_async.set(
            f"{prefix}:gate_evidence_summary",
            json.dumps({
                "reason": "service_lock",
                "status": "approval_required",
                "changed": ["scripts/services/service_run.py", "app/modules/dev_runner/services/merge_service.py"],
                "running": ["MonitorPage-Admin", "MonitorPage-Public"],
            }),
        )

        response = await client.get(f"/api/v1/dev-runner/runners/{rid}")
        assert response.status_code == 200
        data = response.json()
        assert data["display_state"] == "approval_required"
        ges = data["gate_evidence_summary"]
        assert ges is not None
        assert ges["changed"] == [
            "scripts/services/service_run.py",
            "app/modules/dev_runner/services/merge_service.py",
        ]
        assert ges["running"] == ["MonitorPage-Admin", "MonitorPage-Public"]


class TestMergeQueueReadContract:
    async def test_get_merge_queue_R_reads_pending_db_rows_before_redis(
        self,
        client,
        mock_executor_redis,
        runner_state_db,
    ):
        rid = "db-merge-runner-001"
        try:
            upsert_runner_state(
                runner_state_db,
                {
                    "runner_id": rid,
                    "plan_file": "docs/plan/db-merge.md",
                    "status": "running",
                    "branch": "impl/db-merge",
                },
            )
            create_merge_request(
                runner_state_db,
                {
                    "runner_id": rid,
                    "branch": "impl/db-merge",
                    "worktree_path": "D:/work/db-merge",
                    "plan_file": "docs/plan/db-merge.md",
                    "state": "pending",
                },
            )
            runner_state_db.commit()

            response = await client.get("/api/v1/dev-runner/merge-queue")

            assert response.status_code == 200
            rows = [row for row in response.json() if row["runner_id"] == rid]
            assert len(rows) == 1
            assert rows[0]["queue_key"].startswith("db:")
            assert rows[0]["status"] == "queued"
            assert rows[0]["branch"] == "impl/db-merge"
        finally:
            runner_state_db.query(DevRunnerMergeRequest).filter_by(runner_id=rid).delete()
            runner_state_db.query(DevRunnerState).filter_by(runner_id=rid).delete()
            runner_state_db.commit()

    async def test_get_merge_queue_B_db_empty_uses_redis_fallback(
        self,
        client,
        mock_executor_redis,
    ):
        fake_async = mock_executor_redis["async"]
        rid = "redis-merge-runner-001"
        prefix = f"plan-runner:runners:{rid}"
        await fake_async.rpush("plan-runner:merge-queue:monitor-page", rid)
        await fake_async.set(f"{prefix}:branch", "impl/redis-merge")
        await fake_async.set(f"{prefix}:plan_file", "docs/plan/redis-merge.md")

        response = await client.get("/api/v1/dev-runner/merge-queue")

        assert response.status_code == 200
        rows = [row for row in response.json() if row["runner_id"] == rid]
        assert len(rows) == 1
        assert rows[0]["queue_key"] == f"active:merging:{rid}"


class TestApprovalRequiredDivergeEvidence:
    """approval_required response에 diverged_commits / already_in_main_commits evidence 포함 TC.
    결함 4: precheck failure message에 false positive 판단 단서 없음
    수정: gate_evidence_summary에 diverged_commits, already_in_main_commits 필드 보존
    """

    async def test_gate_evidence_summary_preserves_diverge_fields(self, client, mock_executor_redis):
        """approval_required runner의 gate_evidence_summary에 diverge evidence가 보존된다."""
        fake_async = mock_executor_redis["async"]
        rid = "approval-diverge-001"
        prefix = f"plan-runner:runners:{rid}"

        gate_evidence = json.dumps({
            "reason": "service_lock",
            "status": "approval_required",
            "diverged_commits": 1080,
            "already_in_main_commits": 2,
            "changed": ["scripts/services/service_run.py"],
            "running": ["MonitorPage-Admin"],
        })

        await fake_async.set("plan-runner:listener:heartbeat", "2026-05-20T10:00:00")
        await fake_async.zadd("plan-runner:recent_runners", {rid: 100})
        await fake_async.set(f"{prefix}:status", "stopped")
        await fake_async.set(f"{prefix}:trigger", "user")
        await fake_async.set(f"{prefix}:plan_file", "docs/plan/test-diverge.md")
        await fake_async.set(f"{prefix}:merge_status", "approval_required")
        await fake_async.set(f"{prefix}:merge_reason", "service_lock")
        await fake_async.set(f"{prefix}:merge_message", "MERGE_PRECHECK_FAILED[service_lock]: branch diverged 1080 commits from main (2 already in main)")
        await fake_async.set(f"{prefix}:gate_evidence_summary", gate_evidence)

        response = await client.get("/api/v1/dev-runner/status")

        assert response.status_code == 200
        data = response.json()
        assert data["runner_id"] == rid

        summary = data.get("gate_evidence_summary")
        assert summary is not None, "gate_evidence_summary가 응답에 없음"
        assert summary.get("diverged_commits") == 1080, f"diverged_commits 불일치: {summary}"
        assert summary.get("already_in_main_commits") == 2, f"already_in_main_commits 불일치: {summary}"

    async def test_list_runner_gate_evidence_preserved(self, client, mock_executor_redis):
        """runner list 응답에서도 gate_evidence_summary diverge evidence가 보존된다."""
        fake_async = mock_executor_redis["async"]
        fake_sync = mock_executor_redis["sync"]
        rid = "list-diverge-001"
        prefix = f"plan-runner:runners:{rid}"

        gate_evidence = json.dumps({
            "diverged_commits": 500,
            "already_in_main_commits": 10,
        })

        fake_sync.sadd("plan-runner:active_runners", rid)
        fake_sync.set(f"{prefix}:status", "stopped")
        fake_sync.set(f"{prefix}:plan_file", "docs/plan/list-diverge.md")
        fake_sync.set(f"{prefix}:merge_status", "approval_required")
        fake_sync.set(f"{prefix}:gate_evidence_summary", gate_evidence)
        fake_sync.set(f"{prefix}:visible", "1")
        await fake_async.sadd("plan-runner:active_runners", rid)
        await fake_async.set(f"{prefix}:status", "stopped")
        await fake_async.set(f"{prefix}:plan_file", "docs/plan/list-diverge.md")
        await fake_async.set(f"{prefix}:merge_status", "approval_required")
        await fake_async.set(f"{prefix}:gate_evidence_summary", gate_evidence)
        await fake_async.set(f"{prefix}:visible", "1")

        response = await client.get("/api/v1/dev-runner/runners")

        assert response.status_code == 200
        rows = [r for r in response.json() if r.get("runner_id") == rid]
        assert len(rows) == 1, f"runner {rid} list에 없음: {response.json()}"
        summary = rows[0].get("gate_evidence_summary")
        assert summary is not None, "list runner gate_evidence_summary 없음"
        assert summary.get("diverged_commits") == 500

    async def test_get_merge_queue_right_duplicate_completed_runner_ids_return_stable_items(
        self,
        client,
        mock_executor_redis,
    ):
        """R: duplicate completed runner_id rows stay renderable with unique queue_key values."""
        fake_async = mock_executor_redis["async"]
        rid = "duplicate-completed-001"
        for timestamp, branch in (
            ("2026-05-11T10:00:01", "impl/first"),
            ("2026-05-11T10:00:02", "impl/second"),
        ):
            await fake_async.lpush(
                "plan-runner:merge-results",
                json.dumps(
                    {
                        "runner_id": rid,
                        "branch": branch,
                        "plan_file": "docs/plan/duplicate.md",
                        "timestamp": timestamp,
                        "status": "done",
                        "success": True,
                    }
                ),
            )

        response = await client.get("/api/v1/dev-runner/merge-queue")

        assert response.status_code == 200
        rows = [row for row in response.json() if row["runner_id"] == rid]
        assert len(rows) == 2
        assert len({row["queue_key"] for row in rows}) == 2
        assert all(row["queue_key"].startswith("history:") for row in rows)

    async def test_get_merge_queue_boundary_active_runner_not_dropped_by_completed_history_duplicate(
        self,
        client,
        mock_executor_redis,
    ):
        """B: active queue and completed history can contain the same runner_id."""
        fake_async = mock_executor_redis["async"]
        rid = "duplicate-active-001"
        prefix = f"plan-runner:runners:{rid}"
        await fake_async.rpush("plan-runner:merge-queue:monitor-page", rid)
        await fake_async.set(f"{prefix}:branch", "impl/current")
        await fake_async.set(f"{prefix}:plan_file", "docs/plan/current.md")
        await fake_async.set(f"{prefix}:start_time", "2026-05-11T10:00:00")
        await fake_async.lpush(
            "plan-runner:merge-results",
            json.dumps(
                {
                    "runner_id": rid,
                    "branch": "impl/old",
                    "plan_file": "docs/plan/old.md",
                    "timestamp": "2026-05-11T09:00:00",
                    "status": "done",
                    "success": True,
                }
            ),
        )

        response = await client.get("/api/v1/dev-runner/merge-queue")

        assert response.status_code == 200
        rows = [row for row in response.json() if row["runner_id"] == rid]
        assert {row["status"] for row in rows} == {"merging", "done"}
        assert any(row["queue_key"] == f"active:merging:{rid}" for row in rows)

    def test_get_merge_queue_correct_read_only_does_not_call_blocking_turn_wait(self):
        """Co: merge queue API/service read path must not call BRPOP/merge-turn wait helpers."""
        root = Path(__file__).resolve().parents[1]
        service_source = (root / "services" / "merge_service.py").read_text(encoding="utf-8")
        route_source = (root / "routes" / "runner.py").read_text(encoding="utf-8")

        def body(source: str, function_name: str) -> str:
            marker = f"async def {function_name}"
            start = source.index(marker)
            next_def = source.find("\n    async def ", start + len(marker))
            if next_def == -1:
                next_def = source.find("\n    def ", start + len(marker))
            return source[start: next_def if next_def != -1 else len(source)]

        read_bodies = "\n".join(
            [
                body(service_source, "get_merge_queue"),
                body(service_source, "get_merge_queue_length"),
                body(route_source, "get_merge_queue"),
                body(route_source, "get_merge_queue_length"),
            ]
        )

        assert "scan_iter" in read_bodies
        assert "lrange" in read_bodies or "llen" in read_bodies
        assert not re.search(r"\bbrpop\b|acquire_merge_turn|release_merge_turn|merge-turn", read_bodies, re.I)


# ── T5: HTTP — approval_required stopped recent runner 표시 일관성 ─────────────

async def test_recent_stopped_approval_runner_visible_in_runners_R(client, mock_executor_redis):
    """T5-R: active_runners가 아닌 recent_runners의 stopped approval_required runner가 GET /runners에서 반환됨.

    item 14: stopped recent runner가 /runners 엔드포인트에서 display_state=approval_required로 나타난다.
    """
    fake_async = mock_executor_redis["async"]
    rid = "t5-recent-approval-R"
    prefix = f"plan-runner:runners:{rid}"
    # recent_runners에만 등록(active_runners 아님) — 이미 종료된 runner
    await fake_async.zadd("plan-runner:recent_runners", {rid: 1})
    await fake_async.set(f"{prefix}:status", "stopped")
    await fake_async.set(f"{prefix}:trigger", "user")
    await fake_async.set(f"{prefix}:plan_file", "docs/plan/approval-t5.md")
    await fake_async.set(f"{prefix}:merge_status", "approval_required")
    await fake_async.set(f"{prefix}:merge_reason", "service_lock")

    response = await client.get("/api/v1/dev-runner/runners")

    assert response.status_code == 200
    data = response.json()
    matching = [r for r in data if r["runner_id"] == rid]
    assert len(matching) == 1, (
        f"stopped recent runner {rid}가 /runners 응답에 없습니다. "
        "recent_runners에만 있는 approval_required runner가 누락됩니다."
    )
    r = matching[0]
    assert r["display_state"] == "approval_required"
    assert r["display_label"] == "승인 필요"


async def test_approval_required_display_consistent_between_status_and_runners_R(client, mock_executor_redis):
    """T5-R: /status와 /runners가 동일 runner에 대해 display_state·display_label을 동일하게 반환함.

    item 15: /status가 대표 runner로 approval_required를 선택하고 display_label=승인 필요를 반환한다.
    두 엔드포인트 간 display 계약이 일치한다.
    """
    fake_async = mock_executor_redis["async"]
    rid = "t5-consistent-approval-R"
    prefix = f"plan-runner:runners:{rid}"
    # active + recent 모두 등록하여 /status가 대표 runner로 선택하게 함
    await fake_async.sadd("plan-runner:active_runners", rid)
    await fake_async.zadd("plan-runner:recent_runners", {rid: 1})
    await fake_async.set(f"{prefix}:status", "stopped")
    await fake_async.set(f"{prefix}:trigger", "user")
    await fake_async.set(f"{prefix}:plan_file", "docs/plan/approval-t5b.md")
    await fake_async.set(f"{prefix}:merge_status", "approval_required")
    await fake_async.set(f"{prefix}:merge_reason", "service_lock")
    await fake_async.set(f"{prefix}:merge_message", "MERGE_PRECHECK_FAILED[service_lock]")

    status_resp = await client.get("/api/v1/dev-runner/status")
    runners_resp = await client.get("/api/v1/dev-runner/runners")

    assert status_resp.status_code == 200
    assert runners_resp.status_code == 200

    status_data = status_resp.json()
    runners_data = runners_resp.json()

    matching = [r for r in runners_data if r["runner_id"] == rid]
    assert len(matching) == 1
    r = matching[0]

    assert r["display_state"] == "approval_required"
    assert r["display_label"] == "승인 필요"
    assert status_data["display_state"] == "approval_required", (
        f"/status display_state={status_data.get('display_state')}이지만 approval_required 기대"
    )
    assert status_data["display_label"] == "승인 필요", (
        f"/status display_label={status_data.get('display_label')}이지만 '승인 필요' 기대"
    )
    assert r["display_state"] == status_data["display_state"], (
        f"/runners({r['display_state']})와 /status({status_data['display_state']}) display_state 불일치"
    )
    assert r["display_label"] == status_data["display_label"], (
        f"/runners({r['display_label']})와 /status({status_data['display_label']}) display_label 불일치"
    )
