"""
E2E 테스트: Command Listener + Orchestrator 시뮬레이션
(non-http: fakeredis 기반, 실제 프로세스 없음)
"""
import json
import pytest
import fakeredis.aioredis
import fakeredis
from unittest.mock import MagicMock, AsyncMock, patch


def make_executor_service(async_redis, sync_redis=None):
    from app.modules.dev_runner.services.executor_service import ExecutorService
    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = async_redis
    svc.redis_client = sync_redis or MagicMock()
    return svc


def make_merge_queue_item(runner_id: str = "abc12345") -> dict:
    return {
        "runner_id": runner_id,
        "branch": f"runner/{runner_id}",
        "worktree_path": "",
        "plan_file": "/work/docs/plan/test.md",
        "project": "monitor-page",
        "timestamp": "2026-02-26T10:00:00",
        "status": "pending",
    }


class TestOrchestratorE2E:
    """E2E: start-orchestrator 명령 Redis 시뮬레이션"""

    @pytest.mark.asyncio
    async def test_e2e1_start_orchestrator_command_redis_simulation(self):
        """E2E-1: start-orchestrator 명령 → Redis 명령 키에 적재 확인"""
        fake_async = fakeredis.aioredis.FakeRedis(decode_responses=True)

        # start-orchestrator 명령을 Redis 명령 큐에 push (listener 역할 시뮬레이션)
        cmd = {
            "action": "start-orchestrator",
            "runner_id": "orch0001",
            "source": "test",
        }
        await fake_async.lpush("plan-runner:commands", json.dumps(cmd))

        # 명령이 큐에 있는지 확인
        raw = await fake_async.lrange("plan-runner:commands", 0, -1)
        assert len(raw) == 1
        parsed = json.loads(raw[0])
        assert parsed["action"] == "start-orchestrator"

    @pytest.mark.asyncio
    async def test_e2e2_merge_queue_push_and_query(self):
        """E2E-2: Redis merge-queue에 요청 push → get_merge_queue() 조회 확인"""
        fake_async = fakeredis.aioredis.FakeRedis(decode_responses=True)

        item = make_merge_queue_item("runner_e2e")
        await fake_async.lpush("plan-runner:merge-queue", json.dumps(item))

        svc = make_executor_service(fake_async)
        result = await svc.get_merge_queue()

        assert len(result) == 1
        assert result[0]["runner_id"] == "runner_e2e"
        assert result[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_e2e3_get_merge_status(self):
        """E2E-3: get_merge_status(runner_id) → 상태 조회 확인"""
        fake_async = fakeredis.aioredis.FakeRedis(decode_responses=True)

        await fake_async.set("plan-runner:merge:runner_e2e:status", "testing")

        svc = make_executor_service(fake_async)
        result = await svc.get_merge_status("runner_e2e")

        assert result is not None
        assert result["status"] == "testing"

    @pytest.mark.asyncio
    async def test_e2e4_merge_orchestrator_basic_instantiation(self):
        """E2E-4: MergeOrchestrator 인스턴스 생성 + fakeredis로 기본 동작 확인"""
        try:
            from plan_runner.core.merge import MergeOrchestrator, MergeRequest, MergeResult
        except ImportError:
            pytest.skip("plan_runner not available in monitor-page context")

        fake_sync = fakeredis.FakeRedis(decode_responses=True)

        config = MagicMock()
        config.merge_queue_key = "plan-runner:merge-queue"
        config.max_fix_attempts = 3

        orchestrator = MergeOrchestrator(config, fake_sync)

        assert orchestrator is not None
        assert not orchestrator._shutdown

        # 상태 설정 확인
        orchestrator._set_status("test:key", "pending")
        assert fake_sync.get("test:key") == "pending"
