"""ExecutorService 개수 제한 유닛 테스트 — fakeredis 기반"""
import pytest
import fakeredis
import fakeredis.aioredis
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException

from app.modules.dev_runner.services.executor_service import (
    ExecutorService, ACTIVE_RUNNERS_KEY
)
from app.modules.dev_runner.schemas import RunRequest


def make_service_with_fake_redis(fake_sync, fake_async):
    """fakeredis를 주입한 ExecutorService 인스턴스 생성"""
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
    return make_service_with_fake_redis(fake_sync, fake_async)


def _fill_active_runners(fake_sync, count: int):
    for i in range(count):
        fake_sync.sadd(ACTIVE_RUNNERS_KEY, f"runner{i:03d}")


def _mock_settings(max_concurrent: int):
    """settings_service.get() 반환값 mock 생성"""
    mock_settings = MagicMock()
    mock_settings.max_concurrent_runners = max_concurrent
    mock_svc = MagicMock()
    mock_svc.get.return_value = mock_settings
    return mock_svc


# ── 개수 제한 TC ──────────────────────────────────────────────────────────────

class TestRunnerLimit:
    @pytest.mark.asyncio
    async def test_boundary_over_limit_raises_429(self, svc, fake_sync, fake_async):
        """TC-Boundary: MAX=2, 3번째 start → HTTPException(429)"""
        _fill_active_runners(fake_sync, 2)
        # fake_async도 동일하게 채워야 scard가 올바른 값 반환
        for i in range(2):
            await fake_async.sadd(ACTIVE_RUNNERS_KEY, f"runner{i:03d}")

        # _check_redis_and_listener + cleanup_stale_runners bypass (stale 정리가 fake runner 삭제 방지)
        with patch.object(svc, "_check_redis_and_listener", new_callable=AsyncMock), \
             patch.object(svc, "cleanup_stale_runners", new_callable=AsyncMock, return_value={"cleaned_active": 0, "cleaned_recent": 0, "bugs": 0, "total": 0}):
            with patch("app.modules.dev_runner.services.executor_service.settings_service", _mock_settings(2)):
                with pytest.raises(HTTPException) as exc_info:
                    await svc.start_dev_runner(RunRequest(test_source="runner_limit", ))
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_boundary_max1_second_rejected(self, svc, fake_sync, fake_async):
        """TC-Boundary: MAX=1, 1개 start → 성공, 2번째 → 429"""
        await fake_async.sadd(ACTIVE_RUNNERS_KEY, "existing001")

        with patch.object(svc, "_check_redis_and_listener", new_callable=AsyncMock), \
             patch.object(svc, "cleanup_stale_runners", new_callable=AsyncMock, return_value={"cleaned_active": 0, "cleaned_recent": 0, "bugs": 0, "total": 0}):
            with patch("app.modules.dev_runner.services.executor_service.settings_service", _mock_settings(1)):
                with pytest.raises(HTTPException) as exc_info:
                    await svc.start_dev_runner(RunRequest(test_source="runner_limit", ))
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_boundary_max0_rejects_all(self, svc, fake_async):
        """TC-Boundary: MAX=0 → 모든 start 거부"""
        with patch.object(svc, "_check_redis_and_listener", new_callable=AsyncMock), \
             patch.object(svc, "cleanup_stale_runners", new_callable=AsyncMock, return_value={"cleaned_active": 0, "cleaned_recent": 0, "bugs": 0, "total": 0}):
            with patch("app.modules.dev_runner.services.executor_service.settings_service", _mock_settings(0)):
                with pytest.raises(HTTPException) as exc_info:
                    await svc.start_dev_runner(RunRequest(test_source="runner_limit", ))
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_correct_conformance_429_body_contains_counts(self, svc, fake_async):
        """TC-CORRECT-Conformance: 429 응답 body에 현재 실행 수와 최대 수 포함"""
        for i in range(3):
            await fake_async.sadd(ACTIVE_RUNNERS_KEY, f"r{i}")

        with patch.object(svc, "_check_redis_and_listener", new_callable=AsyncMock), \
             patch.object(svc, "cleanup_stale_runners", new_callable=AsyncMock, return_value={"cleaned_active": 0, "cleaned_recent": 0, "bugs": 0, "total": 0}):
            with patch("app.modules.dev_runner.services.executor_service.settings_service", _mock_settings(3)):
                with pytest.raises(HTTPException) as exc_info:
                    await svc.start_dev_runner(RunRequest(test_source="runner_limit", ))
        detail = exc_info.value.detail
        assert "3" in detail  # 최대 수 포함
