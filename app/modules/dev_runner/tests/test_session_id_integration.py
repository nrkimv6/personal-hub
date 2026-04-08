"""session_id 통합 TC (T3) — Redis/파일시스템 실물/fakeredis 기반

start_dev_runner() → Redis command + session_id 키 저장 → get_runner_status() 조회
end-to-end session_id 흐름을 한 번에 검증.
"""

import json
import uuid
from datetime import datetime
from unittest.mock import patch, AsyncMock

import pytest
import fakeredis
import fakeredis.aioredis

from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.services.redis_connection import (
    SESSION_ID_KEY_PREFIX, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY,
)
from app.modules.dev_runner.schemas import RunRequest


@pytest.fixture()
def fake_async():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture()
def fake_sync():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def patch_redis(fake_async, fake_sync):
    with patch.object(executor_service, "async_redis", fake_async), \
         patch.object(executor_service, "redis_client", fake_sync):
        yield


@pytest.fixture(autouse=True)
def patch_check_cleanup():
    async def _noop():
        pass
    with patch.object(executor_service, "_check_redis_and_listener", side_effect=_noop), \
         patch.object(executor_service, "cleanup_stale_runners", side_effect=_noop):
        yield


class TestSessionIdIntegration:
    async def test_redis_to_cmd_full_flow(self, fake_async, fake_sync):
        """E2E: start_dev_runner() → Redis command + session_id 키 저장"""
        captured_cmd = {}

        async def _mock_send(cmd):
            captured_cmd.update(cmd)
            return {"success": True, "runner_id": cmd["runner_id"], "status": "running"}

        with patch.object(executor_service, "_send_command", side_effect=_mock_send), \
             patch.object(executor_service, "_get_runner_fields", new_callable=AsyncMock) as mock_fields:
            mock_fields.return_value = {"pid": None, "plan_file": None, "start_time": None, "execution_count": None}

            req = RunRequest(plan_file="test.md")
            resp = await executor_service.start_dev_runner(req)

        assert resp.session_id is not None
        # command dict에 session_id 포함
        assert captured_cmd.get("session_id") == resp.session_id
        # Redis에 저장됨
        stored = await fake_async.get(f"{SESSION_ID_KEY_PREFIX}{resp.runner_id}")
        assert stored == resp.session_id

    async def test_session_id_persisted_across_status_query(self, fake_async, fake_sync):
        """start 후 get_runner_status() 조회 시 동일 session_id 반환"""
        runner_id = "integ-runner-persist"
        expected_sid = str(uuid.uuid4())

        # Redis에 runner 상태 + session_id 수동 세팅
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "completed")
        await fake_async.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", "claude")
        await fake_async.set(
            f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat()
        )
        await fake_async.set(f"{SESSION_ID_KEY_PREFIX}{runner_id}", expected_sid)

        with patch.object(executor_service, "_correct_pid_state") as mock_pid:
            mock_pid.return_value = (False, None)
            status = await executor_service.get_runner_status(runner_id)

        assert status.session_id == expected_sid

    async def test_concurrent_runners_no_collision(self, fake_async, fake_sync):
        """동시 5개 runner 시작 시 session_id 모두 고유"""
        runner_ids = []
        session_ids = []

        async def _mock_send(cmd):
            runner_ids.append(cmd["runner_id"])
            return {"success": True, "runner_id": cmd["runner_id"], "status": "running"}

        async def _mock_fields(*args, **kwargs):
            return {"pid": None, "plan_file": None, "start_time": None, "execution_count": None}

        with patch.object(executor_service, "_send_command", side_effect=_mock_send), \
             patch.object(executor_service, "_get_runner_fields", side_effect=_mock_fields):

            import asyncio
            tasks = [
                executor_service.start_dev_runner(RunRequest(plan_file=f"plan-{i}.md"))
                for i in range(5)
            ]
            results = await asyncio.gather(*tasks)

        session_ids = [r.session_id for r in results]
        assert len(set(session_ids)) == 5, f"session_id 충돌: {session_ids}"
        for sid in session_ids:
            assert sid is not None
            uuid.UUID(sid)  # UUID 형식 검증
