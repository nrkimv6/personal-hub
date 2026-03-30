"""
TC: ExecutorService.get_merge_queue() v2 — 3개 소스(merging/queued/done) 통합 조회

Phase 3 T1 TC
수정 이력:
  2026-03-30: v2 전환 — merge-lock:*, merge-wait-queue:*, merge-results 3개 소스 통합
"""
import json
import pytest
import fakeredis.aioredis
from unittest.mock import MagicMock


RUNNER_KEY_PREFIX = "plan-runner:runners"


def make_executor_service(async_redis):
    from app.modules.dev_runner.services.executor_service import ExecutorService
    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = async_redis
    svc.redis_client = MagicMock()
    return svc


async def seed_runner_keys(redis, runner_id, branch="impl/test", plan_file="plan.md", worktree="", start_time="2026-03-30T10:00:00"):
    await redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch)
    await redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)
    if worktree:
        await redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", worktree)
    if start_time:
        await redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", start_time)


class TestGetMergeQueueV2:
    @pytest.mark.asyncio
    async def test_get_merge_queue_R_merging_from_lock(self):
        """R: merge-lock:{repo_id} 키에 runner_id가 있을 때 status='merging' 항목 반환"""
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await fake.set("plan-runner:merge-lock:monitor-page", "runner-001")
        await seed_runner_keys(fake, "runner-001")

        svc = make_executor_service(fake)
        result = await svc.get_merge_queue()

        merging = [r for r in result if r["status"] == "merging"]
        assert len(merging) == 1
        assert merging[0]["runner_id"] == "runner-001"
        assert merging[0]["branch"] == "impl/test"

    @pytest.mark.asyncio
    async def test_get_merge_queue_R_queued_from_wait_queue(self):
        """R: merge-wait-queue:{repo_id}에 runner_id가 있을 때 status='queued' 반환"""
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await fake.rpush("plan-runner:merge-wait-queue:monitor-page", "runner-002")
        await seed_runner_keys(fake, "runner-002", branch="impl/feature")

        svc = make_executor_service(fake)
        result = await svc.get_merge_queue()

        queued = [r for r in result if r["status"] == "queued"]
        assert len(queued) == 1
        assert queued[0]["runner_id"] == "runner-002"

    @pytest.mark.asyncio
    async def test_get_merge_queue_R_done_from_results(self):
        """R: merge-results에 완료 이력이 있을 때 status='done'/'failed' 반환"""
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await fake.lpush("plan-runner:merge-results", json.dumps({
            "runner_id": "runner-003",
            "branch": "impl/done",
            "plan_file": "done.md",
            "timestamp": "2026-03-30T09:00:00",
            "status": "done",
            "success": True,
            "message": "",
        }))
        await fake.lpush("plan-runner:merge-results", json.dumps({
            "runner_id": "runner-004",
            "branch": "impl/failed",
            "plan_file": "fail.md",
            "timestamp": "2026-03-30T08:00:00",
            "status": "failed",
            "success": False,
            "message": "merge 실패",
        }))

        svc = make_executor_service(fake)
        result = await svc.get_merge_queue()

        statuses = {r["runner_id"]: r["status"] for r in result}
        assert statuses.get("runner-003") == "done"
        assert statuses.get("runner-004") == "failed"

    @pytest.mark.asyncio
    async def test_get_merge_queue_B_empty_all_sources(self):
        """B: 3개 소스 모두 비어있을 때 빈 리스트 반환"""
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        svc = make_executor_service(fake)
        result = await svc.get_merge_queue()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_merge_queue_B_merging_dedup(self):
        """B: merging runner가 wait-queue에도 있을 때 중복 제거 (merging 우선)"""
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await fake.set("plan-runner:merge-lock:monitor-page", "runner-001")
        await fake.rpush("plan-runner:merge-wait-queue:monitor-page", "runner-001")
        await seed_runner_keys(fake, "runner-001")

        svc = make_executor_service(fake)
        result = await svc.get_merge_queue()

        runner_items = [r for r in result if r["runner_id"] == "runner-001"]
        assert len(runner_items) == 1
        assert runner_items[0]["status"] == "merging"

    @pytest.mark.asyncio
    async def test_get_merge_queue_E_redis_error(self):
        """E: Redis 예외 시 빈 리스트 반환"""
        from unittest.mock import AsyncMock, patch
        import app.modules.dev_runner.services.executor_service as _svc_mod

        svc = make_executor_service(None)
        broken = MagicMock()
        broken.scan_iter.side_effect = Exception("Redis 연결 실패")
        svc.async_redis = broken

        result = await svc.get_merge_queue()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_merge_queue_I_global_lock_compat(self):
        """I: 글로벌 키 plan-runner:merge-lock (suffix 없음) 조회 하위호환"""
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await fake.set("plan-runner:merge-lock", "runner-global")
        await seed_runner_keys(fake, "runner-global", branch="impl/global")

        svc = make_executor_service(fake)
        result = await svc.get_merge_queue()

        merging = [r for r in result if r["runner_id"] == "runner-global"]
        assert len(merging) == 1
        assert merging[0]["status"] == "merging"
