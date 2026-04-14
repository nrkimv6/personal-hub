"""cleanup_stale_runners() 단위 테스트 — RIGHT-BICEP 원칙 + 중복 카운트 버그 수정 TC

대상: app/modules/dev_runner/services/executor_service.py
      ExecutorService.cleanup_stale_runners()

Mock: fakeredis.aioredis (실제 Redis 불필요)
통합(integration): 실제 Redis 연결 필요 (pytest -m integration)
"""

import os
import time
import pytest
import fakeredis
import fakeredis.aioredis
import redis
import redis.asyncio as aioredis
from datetime import datetime, timedelta
from unittest.mock import patch

from app.modules.dev_runner.services.executor_service import (
    ExecutorService,
    ACTIVE_RUNNERS_KEY,
    RECENT_RUNNERS_KEY,
    RECENT_RUNNERS_TTL,
    RUNNER_KEY_PREFIX,
    RUNNER_KEY_SUFFIXES,
)
from tests.dev_runner.merge_test_helpers import resolve_archive_or_history_path


# ─────────────────────────── Fixtures ────────────────────────────

@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def fake_async_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def svc(fake_redis, fake_async_redis):
    """fakeredis 주입된 ExecutorService"""
    service = ExecutorService()
    service.redis_client = fake_redis
    service.async_redis = fake_async_redis
    return service


# ─────────────────────────── helpers ─────────────────────────────

async def _seed_recent(r, rid, *, status, plan_file, start_time_iso=None, score_ts=None):
    """recent_runners에 runner 시드"""
    await r.zadd(RECENT_RUNNERS_KEY, {rid: score_ts if score_ts is not None else time.time()})
    await r.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", status)
    if plan_file:
        await r.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file", plan_file)
    if start_time_iso:
        await r.set(f"{RUNNER_KEY_PREFIX}:{rid}:start_time", start_time_iso)


async def _seed_active(r, rid, *, pid):
    """active_runners에 runner 시드"""
    await r.sadd(ACTIVE_RUNNERS_KEY, rid)
    await r.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", str(pid))
    await r.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")


# ─────────────────────── Right (정상) TC ─────────────────────────

@pytest.mark.asyncio
async def test_cleanup_stale_archived_plan(svc, fake_async_redis, tmp_path):
    """plan 없음 + archive 있음 + stopped + TTL 내 recent → 보존 (R)."""
    archive_file = tmp_path / "archive" / "2026-01-01_foo.md"
    archive_file.parent.mkdir(parents=True)
    archive_file.write_text("archived plan")

    plan_path = str(tmp_path / "plan" / "2026-01-01_foo.md")
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    plan_file_path = str(plan_dir / "2026-01-01_foo.md")

    archive_file2 = resolve_archive_or_history_path(plan_file_path)
    archive_file2.parent.mkdir(parents=True)
    archive_file2.write_text("archived")

    rid = "t-arch-001"
    await _seed_recent(fake_async_redis, rid, status="stopped", plan_file=plan_file_path)

    result = await svc.cleanup_stale_runners()

    assert result["cleaned_recent"] == 0
    assert result["preserved_recent"] == 1
    assert result["bugs"] == 0
    assert result["total"] == 0

    remaining = await fake_async_redis.zrange(RECENT_RUNNERS_KEY, 0, -1)
    assert rid in remaining


@pytest.mark.asyncio
async def test_cleanup_stale_auto_history_plan_R(svc, fake_async_redis, tmp_path):
    """_auto* plan + docs/history + stopped + TTL 내 recent → 정리된다."""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    plan_file_path = str(plan_dir / "2026-02-01_auto-next-cleanup.md")

    history_file = resolve_archive_or_history_path(plan_file_path)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    history_file.write_text("history archived", encoding="utf-8")

    rid = "t-auto-history-001"
    await _seed_recent(fake_async_redis, rid, status="stopped", plan_file=plan_file_path)

    result = await svc.cleanup_stale_runners()

    assert result["cleaned_recent"] == 1
    assert result["preserved_recent"] == 0
    assert result["bugs"] == 0
    assert result["total"] == 1

    remaining = await fake_async_redis.zrange(RECENT_RUNNERS_KEY, 0, -1)
    assert rid not in remaining


@pytest.mark.asyncio
async def test_cleanup_stale_file_lost(svc, fake_async_redis, tmp_path):
    """plan 없음 + archive도 없음 + stopped + TTL 내 recent → 보존 (R)."""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    plan_file_path = str(plan_dir / "2026-02-01_lost.md")

    rid = "t-lost-001"
    await _seed_recent(fake_async_redis, rid, status="stopped", plan_file=plan_file_path)

    result = await svc.cleanup_stale_runners()

    assert result["cleaned_recent"] == 0
    assert result["preserved_recent"] == 1
    assert result["bugs"] == 0
    assert result["total"] == 0

    remaining = await fake_async_redis.zrange(RECENT_RUNNERS_KEY, 0, -1)
    assert rid in remaining


@pytest.mark.asyncio
async def test_cleanup_stale_file_lost_after_ttl_removed(svc, fake_async_redis, tmp_path):
    """plan 없음 + stopped + TTL 초과 recent → stale 정리 + bugs=1 (R)"""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    plan_file_path = str(plan_dir / "2026-02-01_lost_old.md")

    rid = "t-lost-old-001"
    old_ts = time.time() - (RECENT_RUNNERS_TTL + 120)
    await _seed_recent(
        fake_async_redis,
        rid,
        status="stopped",
        plan_file=plan_file_path,
        score_ts=old_ts,
    )

    result = await svc.cleanup_stale_runners()

    assert result["cleaned_recent"] == 1
    assert result["preserved_recent"] == 0
    assert result["bugs"] == 1
    assert result["total"] == 1

    remaining = await fake_async_redis.zrange(RECENT_RUNNERS_KEY, 0, -1)
    assert rid not in remaining


@pytest.mark.asyncio
async def test_cleanup_stale_running_old_file_lost(svc, fake_async_redis, tmp_path):
    """plan 없음 + archive 없음 + running + 10분+ → 정리 + bugs=1 (R)"""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    plan_file_path = str(plan_dir / "2026-02-01_zombie.md")

    old_start = (datetime.now() - timedelta(minutes=20)).isoformat()

    rid = "t-zombie-001"
    await _seed_recent(
        fake_async_redis, rid,
        status="running",
        plan_file=plan_file_path,
        start_time_iso=old_start,
    )

    result = await svc.cleanup_stale_runners()

    assert result["cleaned_recent"] == 1
    assert result["bugs"] == 1

    remaining = await fake_async_redis.zrange(RECENT_RUNNERS_KEY, 0, -1)
    assert rid not in remaining


# ──────────────────────── Boundary TC ────────────────────────────

@pytest.mark.asyncio
async def test_cleanup_stale_running_new_skipped(svc, fake_async_redis, tmp_path):
    """plan 없음 + archive 없음 + running + 10분 미만 → 유예 (스킵) (B)"""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    plan_file_path = str(plan_dir / "2026-02-01_new.md")

    recent_start = (datetime.now() - timedelta(minutes=2)).isoformat()

    rid = "t-new-001"
    await _seed_recent(
        fake_async_redis, rid,
        status="running",
        plan_file=plan_file_path,
        start_time_iso=recent_start,
    )

    result = await svc.cleanup_stale_runners()

    assert result["cleaned_recent"] == 0
    assert result["bugs"] == 0

    remaining = await fake_async_redis.zrange(RECENT_RUNNERS_KEY, 0, -1)
    assert rid in remaining


@pytest.mark.asyncio
async def test_cleanup_stale_plan_exists_skipped(svc, fake_async_redis, tmp_path):
    """plan 파일 존재 → 정리 안 됨 (B)"""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    plan_file = plan_dir / "2026-02-01_exists.md"
    plan_file.write_text("# Active plan")

    rid = "t-exist-001"
    await _seed_recent(
        fake_async_redis, rid,
        status="stopped",
        plan_file=str(plan_file),
    )

    result = await svc.cleanup_stale_runners()

    assert result["cleaned_recent"] == 0
    assert result["total"] == 0

    remaining = await fake_async_redis.zrange(RECENT_RUNNERS_KEY, 0, -1)
    assert rid in remaining


# ─────────────────── active_runners PID 죽음 TC ──────────────────

@pytest.mark.asyncio
async def test_cleanup_stale_dead_pid_active(svc, fake_async_redis):
    """active_runners PID 죽음 → 정리 (R)"""
    rid = "t-dead-pid-001"
    await _seed_active(fake_async_redis, rid, pid=999999999)

    with patch.object(svc, "_is_pid_alive", return_value=False):
        result = await svc.cleanup_stale_runners()

    assert result["cleaned_active"] == 1
    assert result["total"] >= 1

    active_members = await fake_async_redis.smembers(ACTIVE_RUNNERS_KEY)


# ──────────────────────── Error/Empty TC ─────────────────────────

@pytest.mark.asyncio
async def test_cleanup_stale_empty_returns_zero(svc, fake_async_redis):
    """정리 대상 없을 때 0 반환 (E)"""
    result = await svc.cleanup_stale_runners()

    assert result == {
        "cleaned_active": 0,
        "cleaned_recent": 0,
        "preserved_recent": 0,
        "bugs": 0,
        "total": 0,
    }


# ──────────────── Phase1→Phase2 중복 카운트 수정 TC ───────────────

class TestCleanupStaleRunnersDoubleCount:
    """cleanup_stale_runners Phase1→Phase2 중복 카운트 수정 검증"""

    @pytest.mark.asyncio
    async def test_cleanup_stale_dead_pid_no_double_count(self, svc, fake_async_redis):
        """R: dead-PID runner는 Phase1에서 정리되고, Phase2에서 중복 카운트되지 않아야 한다."""
        rid = "t-clnstale-nodbl"
        await _seed_active(fake_async_redis, rid, pid=999999999)

        with patch.object(svc, "_is_pid_alive", return_value=False):
            result = await svc.cleanup_stale_runners()

        assert result["cleaned_active"] == 1
        assert result["cleaned_recent"] == 0
        assert result["bugs"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_stale_dead_pid_not_a_bug(self, svc, fake_async_redis):
        """B: dead-PID runner가 Phase1에서 정리된 경우 bugs는 반드시 0이어야 한다."""
        rid = "t-clnstale-nobug"
        await _seed_active(fake_async_redis, rid, pid=999999999)

        with patch.object(svc, "_is_pid_alive", return_value=False):
            result = await svc.cleanup_stale_runners()

        assert result["bugs"] == 0


# ─────────────────── T3: 통합 TC (실제 Redis) ────────────────────

INTEGRATION_REDIS_DB = 14  # 테스트 전용 DB (운영 DB와 충돌 방지)


@pytest.fixture
def real_redis_sync():
    """실제 Redis 동기 클라이언트 (DB 14, 테스트 전용)"""
    try:
        r = redis.Redis(host="localhost", port=6379, db=INTEGRATION_REDIS_DB, decode_responses=True)
        r.ping()
        yield r
        r.flushdb()
        r.close()
    except (redis.ConnectionError, ConnectionRefusedError):
        pytest.fail("실제 Redis 연결 불가 — 통합 테스트 스킵")


@pytest.fixture
async def real_redis_async(real_redis_sync):
    """실제 Redis 비동기 클라이언트 (DB 14, 테스트 전용)"""
    r = aioredis.Redis(host="localhost", port=6379, db=INTEGRATION_REDIS_DB, decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
def real_svc(real_redis_sync, real_redis_async):
    """실제 Redis가 주입된 ExecutorService"""
    service = ExecutorService()
    service.redis_client = real_redis_sync
    service.async_redis = real_redis_async
    return service


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cleanup_stale_real_redis(real_svc, real_redis_async, tmp_path):
    """실제 Redis: recent_runners에 더미 stale runner 추가 → cleanup → cleaned_recent >= 1 (T3)"""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    plan_file_path = str(plan_dir / "2026-01-01_dummy_stale.md")

    rid = "integration-test-runner-001"

    old_ts = time.time() - (RECENT_RUNNERS_TTL + 120)
    await real_redis_async.zadd(RECENT_RUNNERS_KEY, {rid: old_ts})
    await real_redis_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
    await real_redis_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file", plan_file_path)

    try:
        result = await real_svc.cleanup_stale_runners()

        assert result["cleaned_recent"] >= 1, f"cleaned_recent가 0: {result}"
        assert result["total"] >= 1

        remaining = await real_redis_async.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert rid not in remaining, f"더미 runner가 recent_runners에 여전히 존재: {remaining}"

    finally:
        await real_redis_async.zrem(RECENT_RUNNERS_KEY, rid)
        for suffix in RUNNER_KEY_SUFFIXES:
            await real_redis_async.delete(f"{RUNNER_KEY_PREFIX}:{rid}:{suffix}")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cleanup_stale_preserve_recent_then_dismiss_real_redis(real_svc, real_redis_async, tmp_path):
    """실제 Redis: stopped+TTL내 recent는 보존되고 dismiss 시 즉시 제거된다."""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    plan_file_path = str(plan_dir / "2026-01-01_dummy_recent.md")

    rid = "integration-test-runner-preserve-001"

    await real_redis_async.zadd(RECENT_RUNNERS_KEY, {rid: time.time()})
    await real_redis_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
    await real_redis_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file", plan_file_path)
    await real_redis_async.set(f"{RUNNER_KEY_PREFIX}:{rid}:trigger", "user")

    try:
        result = await real_svc.cleanup_stale_runners()
        assert result["cleaned_recent"] == 0
        assert result["preserved_recent"] >= 1

        remaining = await real_redis_async.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert rid in remaining

        dismissed = await real_svc.dismiss_runner(rid)
        assert dismissed is True

        remaining_after_dismiss = await real_redis_async.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert rid not in remaining_after_dismiss
    finally:
        await real_redis_async.zrem(RECENT_RUNNERS_KEY, rid)
        for suffix in RUNNER_KEY_SUFFIXES:
            await real_redis_async.delete(f"{RUNNER_KEY_PREFIX}:{rid}:{suffix}")
