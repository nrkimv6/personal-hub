"""
TC: ExecutorService.get_merge_queue() / get_merge_status() — fakeredis 기반
"""
import json
import pytest
import fakeredis.aioredis
from unittest.mock import MagicMock, AsyncMock, patch


def make_executor_service(async_redis):
    """ExecutorService 최소 구성 헬퍼 (async_redis 주입)"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = async_redis
    svc.redis_client = MagicMock()
    return svc


def make_queue_item(runner_id: str = "abc12345", status: str = "pending") -> dict:
    return {
        "runner_id": runner_id,
        "branch": f"runner/{runner_id}",
        "worktree_path": "",
        "plan_file": "/work/docs/plan/test.md",
        "project": "monitor-page",
        "timestamp": "2026-02-26T10:00:00",
        "status": status,
    }


# ---------------------------------------------------------------------------
# Phase 10: get_merge_queue() TC
# ---------------------------------------------------------------------------

class TestGetMergeQueue:
    @pytest.mark.asyncio
    async def test_returns_parsed_list(self):
        """TC-Right: get_merge_queue() → Redis LRANGE 결과 파싱하여 list 반환"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

        item = make_queue_item("runner01")
        await fake_redis.lpush("plan-runner:merge-queue", json.dumps(item))

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_queue()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["runner_id"] == "runner01"

    @pytest.mark.asyncio
    async def test_empty_queue_returns_empty_list(self):
        """TC-Boundary: 빈 큐 → 빈 리스트"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_queue()

        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_items_returned(self):
        """TC-Right: 여러 항목 → 모두 반환"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

        for i in range(3):
            await fake_redis.lpush("plan-runner:merge-queue", json.dumps(make_queue_item(f"run{i:04d}")))

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_queue()

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_redis_failure_returns_empty_list(self):
        """TC-Error: Redis 연결 실패 → 빈 리스트 (안전한 응답)"""
        mock_redis = AsyncMock()
        mock_redis.lrange.side_effect = Exception("Redis connection refused")

        svc = make_executor_service(mock_redis)
        result = await svc.get_merge_queue()

        assert result == []


# ---------------------------------------------------------------------------
# Phase 10: get_merge_status() TC
# ---------------------------------------------------------------------------

class TestGetMergeStatus:
    @pytest.mark.asyncio
    async def test_returns_status_dict(self):
        """TC-Right: get_merge_status(runner_id) → 상태 딕셔너리 반환"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await fake_redis.set("plan-runner:merge:abc12345:status", "testing")

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_status("abc12345")

        assert result is not None
        assert result["runner_id"] == "abc12345"
        assert result["status"] == "testing"

    @pytest.mark.asyncio
    async def test_nonexistent_runner_returns_none(self):
        """TC-Boundary: 존재하지 않는 runner_id → None"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_status("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_redis_failure_returns_none(self):
        """TC-Error: Redis 연결 실패 → None (안전한 응답)"""
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = Exception("Redis down")

        svc = make_executor_service(mock_redis)
        result = await svc.get_merge_status("somerunner")

        assert result is None

    @pytest.mark.asyncio
    async def test_status_contains_fix_attempts_key(self):
        """TC-Right: 반환 딕셔너리에 fix_attempts 키 존재"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await fake_redis.set("plan-runner:merge:abc12345:status", "done")

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_status("abc12345")

        assert "fix_attempts" in result
