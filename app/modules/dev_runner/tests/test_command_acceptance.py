import json
from unittest.mock import AsyncMock

import pytest

from app.modules.dev_runner.services.executor_service import COMMANDS_KEY, RESULTS_KEY, ExecutorService


pytestmark = pytest.mark.http


class FakeRedis:
    def __init__(self):
        self.deleted = []
        self.pushed = []
        self.values = {}
        self.brpop = AsyncMock()

    async def ping(self):
        return True

    async def delete(self, key):
        self.deleted.append(key)

    async def lpush(self, key, value):
        self.pushed.append((key, value))

    async def lindex(self, key, index):
        return self.values.get(key)


def make_service(fake: FakeRedis) -> ExecutorService:
    service = ExecutorService.__new__(ExecutorService)
    service.async_redis = fake
    return service


@pytest.mark.asyncio
async def test_runner_command_returns_accepted_without_brpop_R():
    fake = FakeRedis()
    service = make_service(fake)

    result = await service.send_runner_command("runner-1", "force-kill")

    assert result["success"] is True
    assert result["status"] == "accepted"
    assert result["command_id"]
    assert fake.deleted == [f"{RESULTS_KEY}:{result['command_id']}"]
    assert fake.pushed[0][0] == COMMANDS_KEY
    payload = json.loads(fake.pushed[0][1])
    assert payload["action"] == "force-kill"
    assert payload["runner_id"] == "runner-1"
    fake.brpop.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_command_result_pending_without_listener_result_B():
    fake = FakeRedis()
    service = make_service(fake)

    result = await service.get_command_result("abc123")

    assert result["status"] == "pending"
    assert result["command_id"] == "abc123"
    fake.brpop.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_command_result_reads_terminal_result_E():
    fake = FakeRedis()
    fake.values[f"{RESULTS_KEY}:abc123"] = json.dumps({"success": False, "message": "failed"})
    service = make_service(fake)

    result = await service.get_command_result("abc123")

    assert result["status"] == "failed"
    assert result["message"] == "failed"
