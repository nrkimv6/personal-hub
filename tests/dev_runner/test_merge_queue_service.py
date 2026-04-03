"""
TC: ExecutorService.get_merge_queue() / get_merge_status() — fakeredis 기반

수정 이력:
  2026-03-09: get_merge_queue() 구조 변경 — merge-wait-queue에 runner_id 문자열 저장 +
              per-runner Redis 키에서 상세정보 조회하는 방식으로 전환. 기존 JSON 파싱 TC 제거.
  2026-03-30: merge-queue 전환 — merge-wait-queue:* + merge-lock:* → merge-queue:{repo_id} 단일 리스트
"""
import json
import pytest
import fakeredis.aioredis
from unittest.mock import MagicMock, AsyncMock, patch


RUNNER_KEY_PREFIX = "plan-runner:runners"
MERGE_QUEUE_KEY = "plan-runner:merge-queue"


def make_executor_service(async_redis):
    """ExecutorService 최소 구성 헬퍼 (async_redis 주입)"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = async_redis
    svc.redis_client = MagicMock()
    return svc


async def seed_runner(redis, runner_id, plan_file="", branch="", worktree_path="", start_time="", repo_id="monitor-page"):
    """merge-queue:{repo_id}에 runner_id 추가 + per-runner 키 설정"""
    await redis.rpush(f"{MERGE_QUEUE_KEY}:{repo_id}", runner_id)
    if plan_file:
        await redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)
    if branch:
        await redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch)
    if worktree_path:
        await redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", worktree_path)
    if start_time:
        await redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", start_time)


# ---------------------------------------------------------------------------
# get_merge_queue() TC — RIGHT-BICEP + CORRECT
# ---------------------------------------------------------------------------

class TestGetMergeQueue:
    @pytest.mark.asyncio
    async def test_right_returns_list_with_schema_fields(self):
        """Right: runner_id + per-runner 키 → MergeQueueItem 스키마에 맞는 dict 반환"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await seed_runner(fake_redis, "runner01",
                          plan_file="/work/plan/test.md",
                          branch="plan/test",
                          start_time="2026-03-09T17:00:00")

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_queue()

        assert len(result) == 1
        item = result[0]
        assert item["runner_id"] == "runner01"
        assert item["branch"] == "plan/test"
        assert item["plan_file"] == "/work/plan/test.md"
        assert item["project"] == "monitor-page"
        assert item["status"] == "merging"  # index 0(front)는 실행 중 상태
        assert item["timestamp"] == "2026-03-09T17:00:00"

    @pytest.mark.asyncio
    async def test_right_multiple_runners_all_returned(self):
        """Right: 여러 runner → 모두 반환, 순서 유지 (FIFO)"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        for i in range(3):
            await seed_runner(fake_redis, f"run{i:04d}", branch=f"plan/b{i}")

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_queue()

        assert len(result) == 3
        assert [r["runner_id"] for r in result] == ["run0000", "run0001", "run0002"]

    @pytest.mark.asyncio
    async def test_boundary_empty_queue(self):
        """Boundary: 빈 큐 → 빈 리스트"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_queue()
        assert result == []

    @pytest.mark.asyncio
    async def test_boundary_runner_without_per_keys(self):
        """Boundary: per-runner 키 없는 runner_id → 빈 문자열 fallback (에러 아님)"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await fake_redis.rpush(f"{MERGE_QUEUE_KEY}:monitor-page", "orphan_runner")

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_queue()

        assert len(result) == 1
        item = result[0]
        assert item["runner_id"] == "orphan_runner"
        assert item["branch"] == ""
        assert item["plan_file"] == ""
        assert item["timestamp"] == ""

    @pytest.mark.asyncio
    async def test_error_redis_failure_returns_empty(self):
        """Error: Redis 연결 실패 → 빈 리스트 (안전한 응답)"""
        class BrokenRedis:
            def scan_iter(self, *args, **kwargs):
                async def _gen():
                    raise Exception("Redis connection refused")
                    yield ""  # pragma: no cover
                return _gen()

        svc = make_executor_service(BrokenRedis())
        result = await svc.get_merge_queue()
        assert result == []

    @pytest.mark.asyncio
    async def test_correct_pydantic_schema_validation(self):
        """Correct: 반환값이 MergeQueueItem Pydantic 스키마 통과 검증"""
        from app.modules.dev_runner.schemas import MergeQueueItem

        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await seed_runner(fake_redis, "schema_runner",
                          plan_file="test.md", branch="plan/test",
                          start_time="2026-03-09T17:00:00")

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_queue()

        # Pydantic 스키마 생성 시 ValidationError 없어야 함
        item = MergeQueueItem(**result[0])
        assert item.runner_id == "schema_runner"

    @pytest.mark.asyncio
    async def test_correct_partial_per_keys(self):
        """Correct: 일부 per-runner 키만 존재 → 있는 것만 반영, 나머지 빈 문자열"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await fake_redis.rpush(f"{MERGE_QUEUE_KEY}:monitor-page", "partial_runner")
        await fake_redis.set(f"{RUNNER_KEY_PREFIX}:partial_runner:branch", "plan/partial")
        # plan_file, worktree_path, start_time 없음

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_queue()

        item = result[0]
        assert item["branch"] == "plan/partial"
        assert item["plan_file"] == ""
        assert item["worktree_path"] == ""


# ---------------------------------------------------------------------------
# Phase 10: get_merge_status() TC
# ---------------------------------------------------------------------------

class TestGetMergeStatus:
    @pytest.mark.asyncio
    async def test_returns_status_dict(self):
        """TC-Right: get_merge_status(runner_id) → 상태 딕셔너리 반환"""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await fake_redis.set(f"{RUNNER_KEY_PREFIX}:abc12345:merge_status", "testing")

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
        await fake_redis.set(f"{RUNNER_KEY_PREFIX}:abc12345:merge_status", "done")

        svc = make_executor_service(fake_redis)
        result = await svc.get_merge_status("abc12345")

        assert "fix_attempts" in result
