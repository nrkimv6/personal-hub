"""
test_executor_cleanup.py
- cleanup_stale_runners() 중복 카운트 버그 수정 TC

TC 목록:
  R: test_cleanup_stale_dead_pid_no_double_count
  B: test_cleanup_stale_dead_pid_not_a_bug
"""
import pytest
from pathlib import Path
from unittest.mock import patch

try:
    import fakeredis
    import fakeredis.aioredis as fake_aioredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

pytestmark = pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis 미설치")


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def _make_executor_service():
    """fakeredis를 주입한 ExecutorService 인스턴스 반환 (sync + async 모두 세팅)"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    fake_async_r = fake_aioredis.FakeRedis(decode_responses=True)
    fake_sync_r = fakeredis.FakeRedis(decode_responses=True)
    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = fake_async_r
    svc.redis_client = fake_sync_r
    return svc, fake_async_r


async def _seed_active_runner_dead_pid(fake_r, runner_id: str):
    """ACTIVE_RUNNERS에 dead-PID runner를 심는다. plan_file Redis 키는 있으나 파일시스템에는 없음."""
    from app.modules.dev_runner.services.executor_service import (
        RUNNER_KEY_PREFIX,
        ACTIVE_RUNNERS_KEY,
    )
    prefix = f"{RUNNER_KEY_PREFIX}:{runner_id}"
    # dead PID (존재하지 않는 PID)
    await fake_r.set(f"{prefix}:pid", "999999999")
    await fake_r.set(f"{prefix}:status", "running")
    # plan_file: Redis에는 값이 있지만 실제 파일시스템에는 존재하지 않는 경로
    await fake_r.set(f"{prefix}:plan_file", "/nonexistent/plan/file.md")
    await fake_r.sadd(ACTIVE_RUNNERS_KEY, runner_id)


# ──────────────────────────────────────────────
# TC
# ──────────────────────────────────────────────

class TestCleanupStaleRunnersDoubleCount:
    """cleanup_stale_runners Phase1→Phase2 중복 카운트 수정 검증"""

    @pytest.mark.asyncio
    async def test_cleanup_stale_dead_pid_no_double_count(self):
        """R: dead-PID runner는 Phase1에서 정리되고, Phase2에서 중복 카운트되지 않아야 한다.

        기대: cleaned_active=1, cleaned_recent=0, bugs=0
        """
        svc, fake_r = _make_executor_service()
        runner_id = "t-clnstale-nodbl"

        await _seed_active_runner_dead_pid(fake_r, runner_id)

        with patch.object(svc, "_is_pid_alive", return_value=False):
            result = await svc.cleanup_stale_runners()

        assert result["cleaned_active"] == 1, (
            f"cleaned_active는 1이어야 하는데 {result['cleaned_active']}. "
            "Phase1에서 dead-PID runner를 정리하지 못했거나 카운트 누락."
        )
        assert result["cleaned_recent"] == 0, (
            f"cleaned_recent는 0이어야 하는데 {result['cleaned_recent']}. "
            "Phase1에서 이미 정리한 runner가 Phase2에서 중복 카운트됨 — double-count 버그."
        )
        assert result["bugs"] == 0, (
            f"bugs는 0이어야 하는데 {result['bugs']}. "
            "Phase1에서 정상 정리된 runner가 오탐 bugs로 카운트됨."
        )

    @pytest.mark.asyncio
    async def test_cleanup_stale_dead_pid_not_a_bug(self):
        """B: dead-PID runner가 Phase1에서 정리된 경우 bugs는 반드시 0이어야 한다.

        Phase1 처리 ID가 오탐 bugs 카운트에 포함되지 않음 확인.
        """
        svc, fake_r = _make_executor_service()
        runner_id = "t-clnstale-nobug"

        await _seed_active_runner_dead_pid(fake_r, runner_id)

        with patch.object(svc, "_is_pid_alive", return_value=False):
            result = await svc.cleanup_stale_runners()

        assert result["bugs"] == 0, (
            f"bugs == {result['bugs']}. "
            "Phase1에서 정리된 dead-PID runner가 Phase2에서 'running 상태 오탐'으로 "
            "bugs++ 됐을 가능성 있음. cleaned_active_ids 스킵 로직이 동작하지 않는 상태."
        )
