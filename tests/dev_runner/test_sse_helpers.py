"""safe_close_pubsub 헬퍼 단위 테스트 (RIGHT-BICEP)"""
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_safe_close_pubsub_right_normal():
    """R(Right): 정상 pubsub → unsubscribe + punsubscribe + aclose 호출됨."""
    from app.modules.dev_runner.services.sse_helpers import safe_close_pubsub

    pubsub = AsyncMock()
    await safe_close_pubsub(pubsub)

    assert pubsub.unsubscribe.await_count == 1
    assert pubsub.punsubscribe.await_count == 1
    assert pubsub.aclose.await_count == 1


@pytest.mark.asyncio
async def test_safe_close_pubsub_right_none():
    """R(Right): None 전달 → 예외 없이 즉시 반환."""
    from app.modules.dev_runner.services.sse_helpers import safe_close_pubsub

    await safe_close_pubsub(None)  # 예외 없으면 통과


@pytest.mark.asyncio
async def test_safe_close_pubsub_error_aclose_raises_attribute():
    """E(Error): aclose에서 AttributeError → close() fallback 호출."""
    from app.modules.dev_runner.services.sse_helpers import safe_close_pubsub

    pubsub = AsyncMock()
    pubsub.aclose = AsyncMock(side_effect=AttributeError("no aclose"))

    await safe_close_pubsub(pubsub)

    assert pubsub.close.await_count == 1


@pytest.mark.asyncio
async def test_safe_close_pubsub_error_all_fail():
    """E(Error): unsubscribe + punsubscribe + aclose + close 모두 예외 → 전파 없이 정상 반환."""
    from app.modules.dev_runner.services.sse_helpers import safe_close_pubsub

    pubsub = AsyncMock()
    pubsub.unsubscribe = AsyncMock(side_effect=Exception("fail"))
    pubsub.punsubscribe = AsyncMock(side_effect=Exception("fail"))
    pubsub.aclose = AsyncMock(side_effect=AttributeError("fail"))
    pubsub.close = AsyncMock(side_effect=Exception("fail"))

    await safe_close_pubsub(pubsub)  # 예외 없으면 통과


@pytest.mark.asyncio
async def test_safe_close_pubsub_boundary_double_close():
    """B(Boundary): 동일 pubsub에 2회 연속 호출 → 두 번째도 예외 없음."""
    from app.modules.dev_runner.services.sse_helpers import safe_close_pubsub

    pubsub = AsyncMock()
    await safe_close_pubsub(pubsub)
    await safe_close_pubsub(pubsub)

    assert pubsub.aclose.await_count == 2
