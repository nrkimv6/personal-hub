"""ProcessRegistry TC"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_mock_client():
    client = AsyncMock()
    client.hset = AsyncMock(return_value=1)
    client.sadd = AsyncMock(return_value=1)
    client.srem = AsyncMock(return_value=1)
    client.delete = AsyncMock(return_value=1)
    client.hgetall = AsyncMock(return_value={})
    client.keys = AsyncMock(return_value=[])
    client.smembers = AsyncMock(return_value=set())
    return client


@pytest.mark.asyncio
async def test_register_and_get_all_right():
    """R: 정상 등록 후 get_all()에 pid 포함, 필드 값 일치 확인"""
    from app.shared.process.registry import ProcessRegistry

    client = make_mock_client()
    # keys returns one key after register
    key = b"proc:tree:1234"
    entry_data = {
        b"pid": b"1234",
        b"ppid": b"100",
        b"name": b"test-worker",
        b"exe": b"python.exe",
        b"role": b"worker",
        b"registered_at": b"2026-01-01T00:00:00",
        b"memory_mb": b"0",
    }
    client.hgetall.return_value = entry_data
    client.keys.return_value = [key]

    with patch("app.shared.process.registry.RedisClient.get_client", return_value=client):
        registry = ProcessRegistry()
        result = await registry.register(pid=1234, ppid=100, name="test-worker", exe="python.exe", role="worker")
        assert result is True

        all_procs = await registry.get_all()
        assert 1234 in all_procs
        assert all_procs[1234]["name"] == "test-worker"
        assert all_procs[1234]["role"] == "worker"


@pytest.mark.asyncio
async def test_register_redis_disconnected_boundary():
    """B: Redis 미연결 시 register() → False 반환, 예외 아닌 경고"""
    from app.shared.process.registry import ProcessRegistry

    with patch("app.shared.process.registry.RedisClient.get_client", return_value=None):
        registry = ProcessRegistry()
        result = await registry.register(pid=999, ppid=1, name="x", exe="x", role="x")
        assert result is False


@pytest.mark.asyncio
async def test_unregister_removes_from_hash_and_set():
    """R: 등록 → 해제 → get_all()에 미포함 + get_children(ppid)에 미포함"""
    from app.shared.process.registry import ProcessRegistry

    client = make_mock_client()
    # hgetall returns ppid
    client.hgetall.return_value = {b"ppid": b"100"}
    # After unregister, keys returns empty
    client.keys.return_value = []
    client.smembers.return_value = set()

    with patch("app.shared.process.registry.RedisClient.get_client", return_value=client):
        registry = ProcessRegistry()
        result = await registry.unregister(1234)
        assert result is True

        all_procs = await registry.get_all()
        assert 1234 not in all_procs

        children = await registry.get_children(100)
        assert 1234 not in children


@pytest.mark.asyncio
async def test_unregister_nonexistent_pid_boundary():
    """B: 미등록 pid 해제 시 에러 없이 True 반환"""
    from app.shared.process.registry import ProcessRegistry

    client = make_mock_client()
    client.hgetall.return_value = {}  # 빈 결과 = 미등록

    with patch("app.shared.process.registry.RedisClient.get_client", return_value=client):
        registry = ProcessRegistry()
        result = await registry.unregister(99999)
        assert result is True


@pytest.mark.asyncio
async def test_get_children_returns_correct_set():
    """R: 같은 ppid로 3개 등록 → get_children() → 3개 pid set"""
    from app.shared.process.registry import ProcessRegistry

    client = make_mock_client()
    client.smembers.return_value = {b"1", b"2", b"3"}

    with patch("app.shared.process.registry.RedisClient.get_client", return_value=client):
        registry = ProcessRegistry()
        children = await registry.get_children(100)
        assert children == {1, 2, 3}


@pytest.mark.asyncio
async def test_update_memory():
    """R: 등록 후 update_memory(pid, 150.5) → hset 호출 확인"""
    from app.shared.process.registry import ProcessRegistry

    client = make_mock_client()

    with patch("app.shared.process.registry.RedisClient.get_client", return_value=client):
        registry = ProcessRegistry()
        await registry.update_memory(1234, 150.5)
        client.hset.assert_called_with("proc:tree:1234", "memory_mb", "150.5")
