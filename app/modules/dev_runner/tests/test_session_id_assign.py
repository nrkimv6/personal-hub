"""
executor_service.start_dev_runner() — session_id 발급/저장 TC (Phase T1 item 10)
"""
import json
import uuid
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import fakeredis
import fakeredis.aioredis

from app.modules.dev_runner.services.executor_service import executor_service


@pytest.fixture(autouse=True)
def mock_executor_redis():
    fake_sync = fakeredis.FakeRedis(decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mock_claim = MagicMock()
    mock_claim.claim_id = "test-claim-id"
    with patch.object(executor_service, 'redis_client', fake_sync), \
         patch.object(executor_service, 'async_redis', fake_async), \
         patch('app.modules.dev_runner.services.plan_execution_claim_service.claim_plan', return_value=mock_claim):
        yield {"async": fake_async, "sync": fake_sync}


def _brpop_result(runner_id_hint: str = "abc123"):
    key = f"plan-runner:command_results:{runner_id_hint}"
    return (key, json.dumps({"success": True, "message": "Started"}))


async def _run(client, fake_async, payload: dict):
    """POST /run 실행 헬퍼 (heartbeat 세팅 포함)."""
    await fake_async.set("plan-runner:listener:heartbeat", datetime.now().isoformat())
    with patch.object(fake_async, "brpop", new=AsyncMock(return_value=_brpop_result())):
        return await client.post("/api/v1/dev-runner/run", json=payload)


class TestSessionIdAssign:
    async def test_R_auto_generate(self, client, mock_executor_redis):
        """session_id=None → UUID4 자동 생성, 응답 포함"""
        fake_async = mock_executor_redis["async"]
        resp = await _run(client, fake_async, {"plan_file": "test.md"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("session_id") is not None
        # UUID 형식 검증
        sid = data["session_id"]
        uuid.UUID(sid, version=4)  # 형식 오류 시 ValueError

    async def test_R_explicit_use(self, client, mock_executor_redis):
        """명시적 UUID session_id → 응답에 그대로 반영"""
        fake_async = mock_executor_redis["async"]
        explicit_sid = str(uuid.uuid4())
        resp = await _run(client, fake_async, {"plan_file": "test.md", "session_id": explicit_sid})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("session_id") == explicit_sid

    async def test_E_invalid_uuid(self, client, mock_executor_redis):
        """잘못된 UUID 형식 → 자동 재발급 (원본 값 사용 안 함)"""
        fake_async = mock_executor_redis["async"]
        invalid_sid = "not-a-valid-uuid"
        resp = await _run(client, fake_async, {"plan_file": "test.md", "session_id": invalid_sid})
        assert resp.status_code == 200
        data = resp.json()
        sid = data.get("session_id")
        assert sid != invalid_sid
        uuid.UUID(sid, version=4)  # 자동 발급이므로 UUID4 형식

    async def test_B_empty_string(self, client, mock_executor_redis):
        """빈 문자열 → 자동 생성 fallback"""
        fake_async = mock_executor_redis["async"]
        resp = await _run(client, fake_async, {"plan_file": "test.md", "session_id": ""})
        assert resp.status_code == 200
        data = resp.json()
        sid = data.get("session_id")
        assert sid
        uuid.UUID(sid, version=4)  # 자동 생성이므로 UUID4 형식

    async def test_Re_redis_persisted(self, client, mock_executor_redis):
        """SESSION_ID_KEY_PREFIX{runner_id} 키가 Redis에 저장됨 (fakeredis)"""
        from app.modules.dev_runner.services.redis_connection import SESSION_ID_KEY_PREFIX
        fake_async = mock_executor_redis["async"]
        resp = await _run(client, fake_async, {"plan_file": "test.md"})
        assert resp.status_code == 200
        data = resp.json()
        runner_id = data.get("runner_id")
        sid = data.get("session_id")
        assert runner_id and sid
        stored = await fake_async.get(f"{SESSION_ID_KEY_PREFIX}{runner_id}")
        assert stored == sid

    async def test_Re_command_dict_includes(self, client, mock_executor_redis):
        """Redis push command dict에 session_id 포함"""
        fake_async = mock_executor_redis["async"]
        resp = await _run(client, fake_async, {"plan_file": "test.md"})
        assert resp.status_code == 200
        sid = resp.json().get("session_id")

        raw = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert raw, "command queue 비어있음"
        command = json.loads(raw[0])
        assert command.get("session_id") == sid

    async def test_Co_uuid_format(self, client, mock_executor_redis):
        """자동 발급 session_id는 UUID4 형식"""
        fake_async = mock_executor_redis["async"]
        resp = await _run(client, fake_async, {"plan_file": "test.md"})
        assert resp.status_code == 200
        sid = resp.json().get("session_id")
        parsed = uuid.UUID(sid, version=4)
        assert str(parsed) == sid

    async def test_fused_session_command_dict(self, client, mock_executor_redis):
        """fused_session=True → command dict에 fused_session 포함"""
        fake_async = mock_executor_redis["async"]
        resp = await _run(client, fake_async, {"plan_file": "test.md", "fused_session": True})
        assert resp.status_code == 200
        raw = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert raw
        command = json.loads(raw[0])
        assert command.get("fused_session") is True

    async def test_fused_session_false_not_in_command(self, client, mock_executor_redis):
        """fused_session=False → command dict에 fused_session 미포함 (회귀)"""
        fake_async = mock_executor_redis["async"]
        resp = await _run(client, fake_async, {"plan_file": "test.md", "fused_session": False})
        assert resp.status_code == 200
        raw = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert raw
        command = json.loads(raw[0])
        # fused_session=False → key 없거나 falsy
        assert not command.get("fused_session")
