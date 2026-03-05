"""ExecutorService Runner 개수 제한 E2E 테스트 — fakeredis 기반"""
import pytest
import fakeredis
import fakeredis.aioredis
from unittest.mock import patch, AsyncMock, MagicMock
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


def _mock_settings(max_concurrent: int):
    """settings_service.get() 반환값 mock 생성"""
    mock_settings = MagicMock()
    mock_settings.max_concurrent_runners = max_concurrent
    mock_svc = MagicMock()
    mock_svc.get.return_value = mock_settings
    return mock_svc


class TestRunnerLimitE2E:
    @pytest.mark.asyncio
    async def test_e2e_1_third_start_rejected_when_max2(self, svc, fake_async):
        """E2E-1: MAX=2, 3번째 start → 429"""
        # 2개 active runner 등록
        await fake_async.sadd(ACTIVE_RUNNERS_KEY, "r001")
        await fake_async.sadd(ACTIVE_RUNNERS_KEY, "r002")

        with patch.object(svc, "_check_redis_and_listener", new_callable=AsyncMock), \
             patch.object(svc, "_cleanup_stale_runners", new_callable=AsyncMock, return_value=0):
            with patch("app.modules.dev_runner.services.executor_service.settings_service", _mock_settings(2)):
                with pytest.raises(HTTPException) as exc_info:
                    await svc.start_dev_runner(RunRequest(test_source="runner_limit_e2e", ))

        assert exc_info.value.status_code == 429
        assert "2" in exc_info.value.detail
