"""E2E HTTP 테스트: max_cycles=0 (무제한) 버그 수정 검증

실제 FastAPI TestClient + fakeredis를 사용하여 HTTP 레이어부터 Redis command까지
전체 흐름을 검증합니다.

테스트 계층:
  1. HTTP POST /api/v1/dev-runner/run → ExecutorService → Redis LPUSH
  2. Redis에 기록된 command JSON에 max_cycles=0 포함 여부 확인
  3. 실제 Redis 없이도 동작 (fakeredis 주입)
"""

import asyncio
import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock

pytestmark = pytest.mark.http
import fakeredis


@pytest.fixture(autouse=True)
def _plan_runner_redis_db_guard(monkeypatch):
    """fakeredis 주입 테스트에서 conftest Redis db guard를 통과시키기 위한 env var 설정"""
    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")
import fakeredis.aioredis
from fastapi.testclient import TestClient

from app.modules.dev_runner.services.executor_service import ExecutorService, executor_service


# ========== Fixtures ==========


def _build_test_client(**kwargs) -> TestClient:
    from app.main import app
    return TestClient(app, **kwargs)

@pytest.fixture(scope="module")
def client():
    return _build_test_client()


@pytest.fixture
def fake_redis_pair():
    """동기/비동기 fakeredis 쌍 반환"""
    sync_r = fakeredis.FakeRedis(decode_responses=True)
    async_r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return sync_r, async_r


async def _setup_idle_state(async_r, plan_file="test.md"):
    """executor가 idle 상태로 판단하도록 Redis 세팅"""
    await async_r.set("plan-runner:listener:heartbeat", "alive")
    await async_r.set("plan-runner:state:status", "idle")
    await async_r.set("plan-runner:state:pid", "0")
    await async_r.set("plan-runner:state:plan_file", plan_file)
    await async_r.set("plan-runner:state:start_time", datetime.now().isoformat())
    # 참고: per-command result key는 lpush 시점에 intercept하여 seed함


def _make_capture_lpush(async_r, pushed_commands, result_data=None):
    """per-command result key 자동 seed하는 capture_lpush 팩토리"""
    if result_data is None:
        result_data = {"success": True, "pid": 1234}
    orig = async_r.lpush

    async def capture_lpush(key, *vals):
        pushed_commands.extend(vals)
        for v in vals:
            try:
                cmd = json.loads(v)
                if "command_id" in cmd:
                    result_key = f"plan-runner:command_results:{cmd['command_id']}"
                    await orig(result_key, json.dumps(result_data))
            except (json.JSONDecodeError, TypeError):
                pass
        return await orig(key, *vals)

    return capture_lpush


# ========== E2E HTTP: max_cycles=0 ==========

class TestHttpE2EMaxCyclesZero:
    """HTTP 레이어 → Redis command 전파 E2E"""

    def test_post_run_max_cycles_zero_stored_in_redis(self, client, fake_redis_pair):
        """POST /run {max_cycles:0} → Redis command에 max_cycles=0 기록"""
        sync_r, async_r = fake_redis_pair
        asyncio.run(_setup_idle_state(async_r))

        pushed_commands = []

        with patch.object(executor_service, "redis_client", sync_r), \
             patch.object(executor_service, "async_redis", async_r), \
             patch.object(async_r, "lpush", side_effect=_make_capture_lpush(async_r, pushed_commands)):

            resp = client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test.md",
                "max_cycles": 0,
                "test_source": "test_post_run_max_cycles_zero_stored_in_redis"
            })

        assert resp.status_code == 200
        assert len(pushed_commands) >= 1, "Redis에 command가 전달되지 않음"
        cmd = json.loads(pushed_commands[0])
        assert "max_cycles" in cmd, f"max_cycles 키 누락: {cmd}"
        assert cmd["max_cycles"] == 0, f"max_cycles 값 오류: {cmd['max_cycles']}"

    def test_post_run_max_cycles_positive_stored_in_redis(self, client, fake_redis_pair):
        """POST /run {max_cycles:3} → Redis command에 max_cycles=3 기록"""
        sync_r, async_r = fake_redis_pair
        asyncio.run(_setup_idle_state(async_r))

        pushed_commands = []

        with patch.object(executor_service, "redis_client", sync_r), \
             patch.object(executor_service, "async_redis", async_r), \
             patch.object(async_r, "lpush", side_effect=_make_capture_lpush(async_r, pushed_commands)):

            resp = client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test.md",
                "max_cycles": 3,
                "test_source": "test_post_run_max_cycles_positive_stored_in_redis"
            })

        assert resp.status_code == 200
        assert len(pushed_commands) >= 1
        cmd = json.loads(pushed_commands[0])
        assert cmd["max_cycles"] == 3

    def test_post_run_no_max_cycles_uses_default_zero(self, client, fake_redis_pair):
        """POST /run {} → max_cycles 기본값 0 → Redis command에 max_cycles=0"""
        sync_r, async_r = fake_redis_pair
        asyncio.run(_setup_idle_state(async_r))

        pushed_commands = []

        with patch.object(executor_service, "redis_client", sync_r), \
             patch.object(executor_service, "async_redis", async_r), \
             patch.object(async_r, "lpush", side_effect=_make_capture_lpush(async_r, pushed_commands)):

            resp = client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test.md",
                "test_source": "test_post_run_no_max_cycles_uses_default_zero"
            })

        assert resp.status_code == 200
        assert len(pushed_commands) >= 1
        cmd = json.loads(pushed_commands[0])
        # 기본값(0)이 전달되어야 함
        assert "max_cycles" in cmd
        assert cmd["max_cycles"] == 0

    def test_post_run_max_cycles_none_absent_from_redis(self, client, fake_redis_pair):
        """POST /run {max_cycles:null} → Redis command에 max_cycles 키 없음"""
        sync_r, async_r = fake_redis_pair
        asyncio.run(_setup_idle_state(async_r))

        pushed_commands = []

        with patch.object(executor_service, "redis_client", sync_r), \
             patch.object(executor_service, "async_redis", async_r), \
             patch.object(async_r, "lpush", side_effect=_make_capture_lpush(async_r, pushed_commands)):

            resp = client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test.md",
                "max_cycles": None,
                "test_source": "test_post_run_max_cycles_none_absent_from_redis"
            })

        assert resp.status_code == 200
        assert len(pushed_commands) >= 1
        cmd = json.loads(pushed_commands[0])
        assert "max_cycles" not in cmd, f"max_cycles=None인데 command에 포함됨: {cmd}"


# ========== E2E HTTP: 전파 체인 검증 ==========

class TestHttpE2ECommandChain:
    """HTTP 요청 → Redis 기록 전체 체인"""

    def test_action_field_always_run(self, client, fake_redis_pair):
        """POST /run → command.action == 'run'"""
        sync_r, async_r = fake_redis_pair
        asyncio.run(_setup_idle_state(async_r))

        pushed = []

        with patch.object(executor_service, "redis_client", sync_r), \
             patch.object(executor_service, "async_redis", async_r), \
             patch.object(async_r, "lpush", side_effect=_make_capture_lpush(async_r, pushed)):
            resp = client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test.md",
                "max_cycles": 0,
                "test_source": "test_action_field_always_run"
            })

        assert resp.status_code == 200
        assert len(pushed) >= 1
        cmd = json.loads(pushed[0])
        assert cmd["action"] == "run"

    def test_plan_file_forwarded_to_command(self, client, fake_redis_pair):
        """POST /run {plan_file: 'a/b.md'} → command.plan_file == 'a/b.md'"""
        sync_r, async_r = fake_redis_pair
        asyncio.run(_setup_idle_state(async_r, "a/b.md"))

        pushed = []

        with patch.object(executor_service, "redis_client", sync_r), \
             patch.object(executor_service, "async_redis", async_r), \
             patch.object(async_r, "lpush", side_effect=_make_capture_lpush(async_r, pushed)):
            resp = client.post("/api/v1/dev-runner/run", json={
                "plan_file": "a/b.md",
                "max_cycles": 0,
                "test_source": "test_plan_file_forwarded_to_command"
            })

        assert resp.status_code == 200
        assert len(pushed) >= 1
        cmd = json.loads(pushed[0])
        assert cmd["plan_file"] == "a/b.md"

    def test_max_cycles_zero_and_tokens_zero_both_forwarded(self, client, fake_redis_pair):
        """POST /run {max_cycles:0, max_tokens:0} → command에 둘 다 포함"""
        sync_r, async_r = fake_redis_pair
        asyncio.run(_setup_idle_state(async_r))

        pushed = []

        with patch.object(executor_service, "redis_client", sync_r), \
             patch.object(executor_service, "async_redis", async_r), \
             patch.object(async_r, "lpush", side_effect=_make_capture_lpush(async_r, pushed)):
            resp = client.post("/api/v1/dev-runner/run", json={
                "plan_file": "test.md",
                "max_cycles": 0,
                "max_tokens": 0,
                "test_source": "test_max_cycles_zero_and_tokens_zero_both_forwarded"
            })

        assert resp.status_code == 200
        assert len(pushed) >= 1
        cmd = json.loads(pushed[0])
        assert cmd.get("max_cycles") == 0
        assert cmd.get("max_tokens") == 0


# ========== E2E HTTP: 409/503 오류 경로 ==========

class TestHttpE2EErrorPaths:
    """HTTP 오류 응답 검증"""

    def test_post_run_concurrent_creates_new_runner(self, client, fake_redis_pair):
        """멀티 runner: 이미 실행 중이어도 POST /run → 200 + 새 runner_id (409 없음)"""
        sync_r, async_r = fake_redis_pair
        asyncio.run(async_r.set("plan-runner:listener:heartbeat", "alive"))

        pushed = []
        with patch.object(executor_service, "redis_client", sync_r), \
             patch.object(executor_service, "async_redis", async_r), \
             patch.object(async_r, "lpush", side_effect=_make_capture_lpush(async_r, pushed)):
            resp = client.post("/api/v1/dev-runner/run", json={
                "plan_file": "t.md",
                "max_cycles": 0,
                "test_source": "test_post_run_concurrent_creates_new_runner"
            })
        assert resp.status_code == 200
        body = resp.json()
        assert "runner_id" in body
        assert len(body["runner_id"]) > 0

    def test_post_run_redis_down_returns_503(self):
        """Redis 연결 불가 시 POST /run → 503"""
        import redis as redis_lib

        async_mock = AsyncMock()
        async_mock.ping = AsyncMock(side_effect=redis_lib.exceptions.ConnectionError("down"))

        with patch.object(executor_service, "async_redis", async_mock):
            client = _build_test_client(raise_server_exceptions=False)
            resp = client.post("/api/v1/dev-runner/run", json={
                "plan_file": "t.md",
                "max_cycles": 0,
                "test_source": "test_post_run_redis_down_returns_503"
            })
        assert resp.status_code == 503
