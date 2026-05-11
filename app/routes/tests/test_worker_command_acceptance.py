import json

import pytest

from app.modules.system.services.system_utils import (
    get_redis_command_result,
    send_redis_command,
)
from app.routes import worker


pytestmark = pytest.mark.http


class FakeRedis:
    def __init__(self):
        self.deleted = []
        self.pushed = []
        self.values = {}

    async def delete(self, key):
        self.deleted.append(key)

    async def lpush(self, key, value):
        self.pushed.append((key, value))

    async def lindex(self, key, index):
        return self.values.get(key)


@pytest.mark.asyncio
async def test_worker_command_enqueue_returns_accepted_without_brpop(monkeypatch):
    fake = FakeRedis()

    async def fake_get_client():
        return fake

    monkeypatch.setattr("app.shared.redis.client.RedisClient.get_client", fake_get_client)

    result = await worker._send_worker_command("restart")

    assert result["success"] is True
    assert result["status"] == "accepted"
    assert result["command_id"]
    assert fake.deleted == [f"worker:command_results:{result['command_id']}"]
    assert fake.pushed[0][0] == "worker:commands"
    payload = json.loads(fake.pushed[0][1])
    assert payload["command_id"] == result["command_id"]
    assert payload["result_key"] == f"worker:command_results:{result['command_id']}"


@pytest.mark.asyncio
async def test_system_redis_command_enqueue_and_status_read():
    fake = FakeRedis()

    accepted = await send_redis_command(
        fake,
        cmd_key="worker:commands",
        result_key="worker:command_results",
        command=json.dumps({"action": "start"}),
    )

    assert accepted["success"] is True
    assert accepted["status"] == "accepted"
    assert accepted["command_id"]
    assert fake.pushed[0][0] == "worker:commands"

    pending = await get_redis_command_result(fake, "worker:command_results", accepted["command_id"])
    assert pending["status"] == "pending"

    fake.values[f"worker:command_results:{accepted['command_id']}"] = json.dumps(
        {"success": True, "message": "started"}
    )
    completed = await get_redis_command_result(fake, "worker:command_results", accepted["command_id"])
    assert completed["status"] == "completed"
    assert completed["message"] == "started"
