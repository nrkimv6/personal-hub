"""MergeQueue 직접 투입 API TC — RIGHT-BICEP 기반

executor_service.enqueue_merge() 메서드와
POST /merge-queue 엔드포인트를 검증한다.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Fixture — Redis 연결 없이 ExecutorService 인스턴스 생성
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """async_redis를 AsyncMock으로 패치한 ExecutorService 인스턴스 (Redis 연결 없이)"""
    with (
        patch("redis.Redis"),
        patch("redis.asyncio.Redis"),
    ):
        from app.modules.dev_runner.services.executor_service import ExecutorService
        svc = ExecutorService()
        svc.async_redis = AsyncMock()
        return svc


# ---------------------------------------------------------------------------
# RIGHT: 정상 동작 검증
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_merge_success(service):
    """R: enqueue_merge() 정상 호출 → lpush 1회, runner_id=manual- prefix, queued=True"""
    result = await service.enqueue_merge(branch="plan/test-branch")

    # lpush 1회 호출 확인
    service.async_redis.lpush.assert_awaited_once()
    call_args = service.async_redis.lpush.call_args
    assert call_args[0][0] == "plan-runner:merge-queue"

    # JSON 파싱 및 runner_id 검증
    payload = json.loads(call_args[0][1])
    assert payload["runner_id"].startswith("manual-")

    # 반환값 검증
    assert result["queued"] is True
    assert result["runner_id"].startswith("manual-")


@pytest.mark.asyncio
async def test_enqueue_merge_default_values(service):
    """B: 기본값 검증 — project=monitor-page, plan_file="", worktree_path="", status=pending"""
    await service.enqueue_merge(branch="test")

    call_args = service.async_redis.lpush.call_args
    payload = json.loads(call_args[0][1])

    assert payload["project"] == "monitor-page"
    assert payload["plan_file"] == ""
    assert payload["worktree_path"] == ""
    assert payload["status"] == "pending"


@pytest.mark.asyncio
async def test_enqueue_merge_custom_project(service):
    """R: project 커스텀 지정 → JSON의 project 필드에 반영"""
    await service.enqueue_merge(branch="test", project="wtools")

    call_args = service.async_redis.lpush.call_args
    payload = json.loads(call_args[0][1])

    assert payload["project"] == "wtools"


@pytest.mark.asyncio
async def test_enqueue_merge_redis_down(service):
    """E: Redis lpush 실패 시 예외 전파"""
    service.async_redis.lpush.side_effect = ConnectionError("refused")

    with pytest.raises(ConnectionError):
        await service.enqueue_merge(branch="test")
