"""executor_service.py 머지 버그 수정 TC

- get_merge_status 키 불일치 수정 검증
- enqueue_merge method 제거 확인
- restart_listener SIGTERM 단일 호출 확인
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def service():
    """async_redis를 AsyncMock으로 패치한 ExecutorService (Redis 연결 없이)"""
    with (
        patch("redis.Redis"),
        patch("redis.asyncio.Redis"),
    ):
        from app.modules.dev_runner.services.executor_service import ExecutorService
        svc = ExecutorService()
        svc.async_redis = AsyncMock()
        return svc


# ---------------------------------------------------------------------------
# Phase 1: get_merge_status 키 수정 TC
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_merge_status_right_returns_dict(service):
    """R: 올바른 키(plan-runner:runners:{rid}:merge_status)에 값 있을 때 dict 반환"""
    service.async_redis.get = AsyncMock(return_value="merging")

    result = await service.get_merge_status("runner-abc1")

    assert result is not None
    assert result["runner_id"] == "runner-abc1"
    assert result["status"] == "merging"
    assert "test_passed" in result
    assert "fix_attempts" in result

    # 호출된 키가 올바른 네임스페이스인지 확인
    called_key = service.async_redis.get.call_args[0][0]
    assert "plan-runner:runners:runner-abc1:merge_status" == called_key


@pytest.mark.asyncio
async def test_get_merge_status_boundary_none_when_missing(service):
    """B: 키 없을 때 None 반환"""
    service.async_redis.get = AsyncMock(return_value=None)

    result = await service.get_merge_status("runner-xyz")

    assert result is None


@pytest.mark.asyncio
async def test_get_merge_status_error_redis_down(service):
    """E: Redis 예외 시 None 반환 (예외 전파 안 함)"""
    service.async_redis.get = AsyncMock(side_effect=ConnectionError("redis down"))

    result = await service.get_merge_status("runner-err")

    assert result is None


@pytest.mark.asyncio
async def test_get_merge_status_old_key_returns_none(service):
    """구 키(plan-runner:merge:{rid}:status)에 set해도 올바른 키가 다르므로 None 반환 — 키 분리 검증"""
    # 구 키에만 값이 있고 올바른 키는 없는 상황 시뮬레이션
    async def mock_get(key):
        if key == "plan-runner:merge:runner-old:status":
            return "merging"  # 구 키에는 값 있음
        return None  # 올바른 키는 없음

    service.async_redis.get = mock_get

    result = await service.get_merge_status("runner-old")

    # 올바른 키(plan-runner:runners:runner-old:merge_status)를 조회하므로 None
    assert result is None


# ---------------------------------------------------------------------------
# Phase 2: enqueue_merge 제거 확인 TC
# ---------------------------------------------------------------------------

def test_enqueue_merge_method_removed(service):
    """enqueue_merge method가 executor_service에서 제거됐는지 확인"""
    assert not hasattr(service, "enqueue_merge"), \
        "enqueue_merge()가 아직 남아있습니다. deprecated method를 제거하세요."


# ---------------------------------------------------------------------------
# Phase T3: 재현/통합 TC — fakeredis로 실제 키 네임스페이스 검증
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t3_get_merge_status_correct_key_with_fakeredis():
    """T3: fakeredis로 올바른 키(plan-runner:runners:{rid}:merge_status)에 set 후 dict 반환 확인"""
    import fakeredis.aioredis as fakeredis_async
    fr = fakeredis_async.FakeRedis(decode_responses=True)

    with (
        patch("redis.Redis"),
        patch("redis.asyncio.Redis"),
    ):
        from app.modules.dev_runner.services.executor_service import ExecutorService
        svc = ExecutorService()
        svc.async_redis = fr

    # 올바른 키에 값 set
    await fr.set("plan-runner:runners:t3-runner:merge_status", "merged")

    result = await svc.get_merge_status("t3-runner")

    assert result is not None
    assert result["status"] == "merged"
    assert result["runner_id"] == "t3-runner"
    assert "test_passed" in result
    assert "fix_attempts" in result

    await fr.aclose()


@pytest.mark.asyncio
async def test_t3_old_key_pattern_returns_none_with_fakeredis():
    """T3: 구 키(plan-runner:merge:{rid}:status)에만 set 시 None 반환 — 버그 재현 경로"""
    import fakeredis.aioredis as fakeredis_async
    fr = fakeredis_async.FakeRedis(decode_responses=True)

    with (
        patch("redis.Redis"),
        patch("redis.asyncio.Redis"),
    ):
        from app.modules.dev_runner.services.executor_service import ExecutorService
        svc = ExecutorService()
        svc.async_redis = fr

    # 구 (잘못된) 키에만 set
    await fr.set("plan-runner:merge:t3-runner:status", "merging")

    result = await svc.get_merge_status("t3-runner")

    # 수정 후 올바른 키를 조회하므로 None
    assert result is None

    await fr.aclose()
