"""visible 노출 버그 재현/통합 TC

Phase T3: fakeredis로 실제 get_all_runners() 호출.
근본 원인 재현: test_source 누락 → trigger="api" → 이전 코드면 visible=True (버그), 수정 후 visible=False (정상).
"""

import pytest
import asyncio
import fakeredis.aioredis
from unittest.mock import patch, MagicMock

from app.modules.dev_runner.services.executor_service import ExecutorService

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"


async def _make_executor_with_fakeredis():
    """fakeredis를 주입한 ExecutorService 인스턴스 생성 (decode_responses=True: str 반환)"""
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = fake_redis
    return svc, fake_redis


async def _seed_runner(fake_redis, runner_id: str, trigger: str | None, status: str = "running"):
    """fakeredis에 runner 키를 직접 세팅"""
    await fake_redis.sadd(ACTIVE_RUNNERS_KEY, runner_id)
    await fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", status)
    await fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")
    if trigger is not None:
        await fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", trigger)
    # trigger 키를 세팅하지 않으면 Redis에서 None 반환 → TTL 만료/소실 시나리오


# ══════════════════════════════════════════════════════════════════════════════
# 재현 TC: 화이트리스트 전환 후 fail-closed 검증
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_reproduce_visible_leak_missing_test_source():
    """재현: test_source 누락 시 trigger="api" → get_all_runners() → visible=False (fail-closed)

    버그 재발 시나리오: test_source 없이 RunRequest 생성 → executor_service가 trigger="api" 설정.
    화이트리스트 전환 전: visible=True (버그)
    화이트리스트 전환 후: visible=False (정상 — 이 TC가 검증)
    """
    svc, fake_redis = await _make_executor_with_fakeredis()
    runner_id = "leak-test-001"
    # test_source 누락 시나리오: trigger="api" (executor_service 기본 폴백)
    await _seed_runner(fake_redis, runner_id, trigger="api")

    # DB 세션 mock (orphan 판별용)
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.database.SessionLocal", return_value=mock_db):
        runners = await svc.get_all_runners()

    assert len(runners) == 1
    runner = runners[0]
    assert runner.runner_id == runner_id
    assert runner.trigger == "api"
    assert runner.visible is False, (
        f"trigger='api' runner가 visible=True! "
        f"화이트리스트 전환이 제대로 적용되지 않았습니다. visible={runner.visible!r}"
    )


@pytest.mark.asyncio
async def test_reproduce_visible_leak_trigger_none():
    """재현: trigger 키 소실 시나리오 → get_all_runners() → visible=False (fail-closed)

    버그 재발 시나리오: RUNNER_KEY_SUFFIXES에서 trigger 누락 → TTL 미설정 → runner cleanup 후 trigger 키 소실.
    화이트리스트 전환 전: visible=True (버그)
    화이트리스트 전환 후: visible=False (정상)
    """
    svc, fake_redis = await _make_executor_with_fakeredis()
    runner_id = "leak-test-002"
    # trigger 키를 아예 세팅하지 않음 (TTL 만료/소실 시나리오)
    await _seed_runner(fake_redis, runner_id, trigger=None)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.database.SessionLocal", return_value=mock_db):
        runners = await svc.get_all_runners()

    assert len(runners) == 1
    runner = runners[0]
    assert runner.runner_id == runner_id
    assert runner.trigger is None
    assert runner.visible is False, (
        f"trigger=None runner가 visible=True! "
        f"화이트리스트 전환이 제대로 적용되지 않았습니다. visible={runner.visible!r}"
    )


@pytest.mark.asyncio
async def test_user_trigger_visible_true_integration():
    """통합: trigger="user" → get_all_runners() → visible=True (프론트엔드 정상 표시)"""
    svc, fake_redis = await _make_executor_with_fakeredis()
    runner_id = "user-runner-001"
    await _seed_runner(fake_redis, runner_id, trigger="user")

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.database.SessionLocal", return_value=mock_db):
        runners = await svc.get_all_runners()

    assert len(runners) == 1
    runner = runners[0]
    assert runner.visible is True, (
        f"trigger='user' runner가 visible=False! "
        f"프론트엔드에서 사용자 실행 runner가 표시되지 않습니다. visible={runner.visible!r}"
    )
