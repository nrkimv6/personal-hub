"""ExecutorService Runner 개수 제한 E2E 테스트 — fakeredis 기반"""
import pytest
import fakeredis
import fakeredis.aioredis
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException

from app.modules.dev_runner.services.executor_service import (
    ExecutorService, ACTIVE_RUNNERS_KEY
)
from app.modules.dev_runner.schemas import RunRequest


def make_svc(fake_sync, fake_async):
    svc = ExecutorService.__new__(ExecutorService)
    svc.redis_client = fake_sync
    svc.async_redis = fake_async
    return svc


@pytest.fixture
def fake_sync():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def fake_async():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def svc(fake_sync, fake_async):
    return make_svc(fake_sync, fake_async)


class TestRunnerLimitE2E:
    @pytest.mark.asyncio
    async def test_e2e_1_third_start_rejected_when_max2(self, svc, fake_async):
        """E2E-1: MAX=2, 3번째 start → 429"""
        # 2개 active runner 등록
        await fake_async.sadd(ACTIVE_RUNNERS_KEY, "r001")
        await fake_async.sadd(ACTIVE_RUNNERS_KEY, "r002")

        with patch.object(svc, "_check_redis_and_listener", new_callable=AsyncMock):
            with patch("app.modules.dev_runner.services.executor_service.config") as mock_cfg:
                mock_cfg.MAX_CONCURRENT_RUNNERS = 2
                with pytest.raises(HTTPException) as exc_info:
                    await svc.start_dev_runner(RunRequest())

        assert exc_info.value.status_code == 429
        assert "2" in exc_info.value.detail
