"""RunStatusResponse.session_id 필드 — 저장/조회/직렬화 TC (T1)

get_runner_status()가 Redis에서 session_id를 읽고 RunStatusResponse에 채우는지 검증.
"""

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
import fakeredis.aioredis

from app.modules.dev_runner.schemas import RunStatusResponse
from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.services.redis_connection import (
    SESSION_ID_KEY_PREFIX, RUNNER_KEY_PREFIX,
)


@pytest.fixture()
def fake_async():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def patch_redis(fake_async):
    import fakeredis
    fake_sync = fakeredis.FakeRedis(decode_responses=True)
    with patch.object(executor_service, "async_redis", fake_async), \
         patch.object(executor_service, "redis_client", fake_sync):
        yield


async def _seed_runner(fake_async, runner_id: str, session_id: str = None):
    """Redis에 runner 상태 + session_id 세팅"""
    await fake_async.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "completed")
    await fake_async.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", "claude")
    await fake_async.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat())
    if session_id is not None:
        await fake_async.set(f"{SESSION_ID_KEY_PREFIX}{runner_id}", session_id)


class TestStateSessionId:
    async def test_R_roundtrip(self, fake_async):
        """R: save(session_id) → get_runner_status() → 동일 session_id 반환"""
        runner_id = "test-runner-sid-roundtrip"
        expected_sid = str(uuid.uuid4())
        await _seed_runner(fake_async, runner_id, session_id=expected_sid)

        with patch.object(executor_service, "_correct_pid_state") as mock_pid:
            mock_pid.return_value = (False, None)
            resp = await executor_service.get_runner_status(runner_id)

        assert resp.session_id == expected_sid

    async def test_E_legacy_state(self, fake_async):
        """E: session_id 키 없는 기존 runner → session_id=None 반환 (하위 호환)"""
        runner_id = "test-runner-legacy"
        await _seed_runner(fake_async, runner_id, session_id=None)  # session_id 키 없음

        with patch.object(executor_service, "_correct_pid_state") as mock_pid:
            mock_pid.return_value = (False, None)
            resp = await executor_service.get_runner_status(runner_id)

        assert resp.session_id is None

    async def test_Re_response_field(self, fake_async):
        """Re: RunStatusResponse.session_id 필드가 JSON 직렬화에 포함됨"""
        sid = str(uuid.uuid4())
        resp = RunStatusResponse(
            running=False,
            session_id=sid,
        )
        data = resp.model_dump()
        assert "session_id" in data
        assert data["session_id"] == sid
