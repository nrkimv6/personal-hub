import json
from unittest.mock import AsyncMock

import pytest

from app.modules.dev_runner.services.executor_service import COMMANDS_KEY, RESULTS_KEY, ExecutorService
from app.modules.dev_runner.schemas import RunRequest


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

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value

    async def scard(self, key):
        return 0

    async def srem(self, key, value):
        return 1


def make_service(fake: FakeRedis) -> ExecutorService:
    service = ExecutorService.__new__(ExecutorService)
    service.async_redis = fake
    service.cleanup_stale_runners = AsyncMock(return_value={})
    service._best_effort_upsert_runner_state = lambda payload: None
    service._runner_key = lambda rid, suffix: f"runner:{rid}:{suffix}"
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


@pytest.mark.asyncio
async def test_start_dev_runner_returns_without_brpop_B(monkeypatch):
    fake = FakeRedis()
    fake.values["plan-runner:listener:heartbeat"] = "alive"
    service = make_service(fake)

    monkeypatch.setattr(
        "app.modules.dev_runner.services.executor_service.settings_service.get",
        lambda: type("Settings", (), {"max_concurrent_runners": 5, "default_engine": "claude", "default_fix_engine": "claude"})(),
    )

    result = await service.start_dev_runner(RunRequest(plan_file=None, trigger="test"))

    assert result.running is True
    assert result.runner_id
    assert result.listener_alive is True
    fake.brpop.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_dev_runner_returns_without_brpop_R():
    fake = FakeRedis()
    service = make_service(fake)
    fake.values[service._runner_key("runner-1", "status")] = "running"

    result = await service.stop_dev_runner("runner-1")

    assert result["success"] is True
    assert result["status"] == "accepted"
    assert result["command_id"]
    fake.brpop.assert_not_awaited()
