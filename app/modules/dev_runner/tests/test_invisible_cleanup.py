"""test_invisible_cleanup.py — invisible runner 유입 차단 + 즉시 정리 TC

RIGHT-BICEP + CORRECT:
  R — 정상 동작
  B — 경계값
  T3 — 재현/통합 TC
"""
import time
from unittest.mock import MagicMock, patch

import fakeredis
import fakeredis.aioredis
import pytest

from app.modules.dev_runner.services.executor_service import (
    executor_service,
    ACTIVE_RUNNERS_KEY,
    RECENT_RUNNERS_KEY,
    RUNNER_KEY_PREFIX,
    RUNNER_KEY_SUFFIXES,
)


# ---------------------------------------------------------------------------
# 공통 fixture: executor_service의 sync/async redis를 fakeredis로 교체
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_redis_pair():
    """executor_service의 redis_client + async_redis를 FakeServer 공유 fakeredis로 교체."""
    server = fakeredis.FakeServer()
    fake_sync = fakeredis.FakeRedis(server=server, decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_session_local = MagicMock(return_value=mock_db)

    with patch.object(executor_service, 'redis_client', fake_sync), \
         patch.object(executor_service, 'async_redis', fake_async), \
         patch('app.database.SessionLocal', mock_session_local):
        yield fake_sync, fake_async


# ---------------------------------------------------------------------------
# Phase 3 / Item 6: _force_cleanup_state invisible 방어 TC
# ---------------------------------------------------------------------------

class TestForceCleanupInvisibleDefense:

    @pytest.mark.asyncio
    async def test_force_cleanup_batch_skips_invisible_zadd_right(self, fake_redis_pair):
        """R(Right): 배치 정리 시 invisible runner는 RECENT에 등록되지 않고 키 즉시 삭제"""
        fake, _ = fake_redis_pair
        invisible_rids = ["invis-001", "invis-002", "invis-003"]
        visible_rid = "vis-user-001"

        # invisible runners (trigger 없음) — RECENT 오염 후보
        for rid in invisible_rids:
            fake.sadd(ACTIVE_RUNNERS_KEY, rid)
            fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")

        # visible runner (trigger="user") — RECENT 보존 대상
        fake.sadd(ACTIVE_RUNNERS_KEY, visible_rid)
        fake.set(f"{RUNNER_KEY_PREFIX}:{visible_rid}:status", "running")
        fake.set(f"{RUNNER_KEY_PREFIX}:{visible_rid}:trigger", "user")

        # 배치 정리 (runner_id="" → 전체 정리)
        await executor_service._force_cleanup_state()

        recent_ids = fake.zrange(RECENT_RUNNERS_KEY, 0, -1)

        # visible runner만 RECENT에 포함되어야 함
        assert visible_rid in recent_ids, "trigger='user' 러너는 RECENT에 보존되어야 함"

        # invisible runner는 RECENT에 없어야 함
        for rid in invisible_rids:
            assert rid not in recent_ids, f"invisible runner({rid})가 RECENT에 등록되면 안 됨"
            # per-runner 키 전체 삭제 확인 (고아 키 방지)
            status = fake.get(f"{RUNNER_KEY_PREFIX}:{rid}:status")
            assert status is None, f"invisible runner({rid}) per-runner 키가 삭제되어야 함"

    @pytest.mark.asyncio
    async def test_force_cleanup_single_skips_invisible_zadd_right(self, fake_redis_pair):
        """R(Right): 개별 정리 시 invisible runner는 RECENT 미등록 + 키 삭제"""
        fake, _ = fake_redis_pair
        rid = "invis-single-001"

        fake.sadd(ACTIVE_RUNNERS_KEY, rid)
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        # trigger 미설정 = invisible

        await executor_service._force_cleanup_state(rid)

        recent_ids = fake.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert rid not in recent_ids, "invisible runner가 RECENT에 등록되면 안 됨"

        # ACTIVE에서도 제거됨
        assert not fake.sismember(ACTIVE_RUNNERS_KEY, rid)

        # per-runner 키 삭제 확인
        for suffix in RUNNER_KEY_SUFFIXES:
            val = fake.get(f"{RUNNER_KEY_PREFIX}:{rid}:{suffix}")
            assert val is None, f"invisible runner per-runner 키({suffix})가 삭제되어야 함"

    @pytest.mark.asyncio
    async def test_force_cleanup_visible_runner_zadd_right(self, fake_redis_pair):
        """R(Right): visible runner(trigger='user')는 RECENT에 등록됨"""
        fake, _ = fake_redis_pair
        rid = "vis-user-only-001"

        fake.sadd(ACTIVE_RUNNERS_KEY, rid)
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:trigger", "user")

        await executor_service._force_cleanup_state(rid)

        # ACTIVE에서 제거됨
        assert not fake.sismember(ACTIVE_RUNNERS_KEY, rid)

        # RECENT에 등록됨
        score = fake.zscore(RECENT_RUNNERS_KEY, rid)
        assert score is not None, "trigger='user' 러너는 RECENT에 등록되어야 함"

        # status가 stopped로 변경됨
        assert fake.get(f"{RUNNER_KEY_PREFIX}:{rid}:status") == "stopped"


# ---------------------------------------------------------------------------
# Phase 3 / Item 7: cleanup_stale_runners invisible 정리 TC
# ---------------------------------------------------------------------------

class TestCleanupStaleInvisible:

    @pytest.mark.asyncio
    async def test_cleanup_stale_removes_invisible_within_ttl_right(self, fake_redis_pair):
        """R(Right): invisible stopped runner는 TTL 내여도 즉시 정리됨 (수정 전: 보존됨)"""
        fake, _ = fake_redis_pair
        rid = "invis-stale-001"

        # TTL 내 (최근 종료) invisible stopped runner
        fake.zadd(RECENT_RUNNERS_KEY, {rid: time.time()})
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
        # trigger 미설정 = invisible

        result = await executor_service.cleanup_stale_runners()

        # cleaned_recent에 포함됨
        assert result["cleaned_recent"] >= 1, "invisible runner는 cleaned_recent에 포함되어야 함"

        # RECENT에서 제거됨
        recent_ids = fake.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert rid not in recent_ids, "invisible stopped runner는 TTL 내여도 RECENT에서 제거되어야 함"

    @pytest.mark.asyncio
    async def test_cleanup_stale_preserves_visible_within_ttl_boundary(self, fake_redis_pair):
        """B(Boundary): visible stopped runner는 TTL 내이면 preserve됨 (dismiss 전까지 보존)"""
        fake, _ = fake_redis_pair
        rid = "vis-stale-keep-001"

        # TTL 내 visible stopped runner
        fake.zadd(RECENT_RUNNERS_KEY, {rid: time.time()})
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:trigger", "user")

        result = await executor_service.cleanup_stale_runners()

        assert result["cleaned_recent"] == 0, "visible runner는 cleaned_recent에 포함되면 안 됨"
        assert result.get("preserved_recent", 0) == 1, "visible runner는 preserved_recent에 포함되어야 함"

        recent_ids = fake.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert rid in recent_ids, "trigger='user' stopped runner는 RECENT에 보존되어야 함"


# ---------------------------------------------------------------------------
# Phase 4 / Item 8: SSE _cleanup_invisible_recent_runners TC
# ---------------------------------------------------------------------------

class TestCleanupInvisibleRecentRunners:

    def _make_event_service_with_fake_sync(self, fake_sync):
        """EventService를 __init__ 없이 생성하고 _sync에 fakeredis 주입"""
        from app.modules.dev_runner.services.event_service import EventService
        svc = EventService.__new__(EventService)
        svc._sync = fake_sync
        return svc

    def test_cleanup_invisible_recent_runners_removes_invisible_right(self):
        """R(Right): _cleanup_invisible_recent_runners()가 trigger=None runner를 RECENT에서 제거"""
        from app.modules.dev_runner.services.event_service import (
            RECENT_RUNNERS_KEY as EVT_RECENT_KEY,
            RUNNER_KEY_PREFIX as EVT_PREFIX,
        )
        fake = fakeredis.FakeRedis(decode_responses=True)

        # invisible runner 5개 + visible runner 2개
        for i in range(5):
            rid = f"invis-sse-{i:03d}"
            fake.zadd(EVT_RECENT_KEY, {rid: float(i + 1)})
            # trigger 미설정 = invisible

        for i in range(2):
            rid = f"vis-sse-{i:03d}"
            fake.zadd(EVT_RECENT_KEY, {rid: float(i + 100)})
            fake.set(f"{EVT_PREFIX}:{rid}:trigger", "user")

        assert fake.zcard(EVT_RECENT_KEY) == 7

        svc = self._make_event_service_with_fake_sync(fake)
        svc._cleanup_invisible_recent_runners()

        remaining = fake.zrange(EVT_RECENT_KEY, 0, -1)
        assert len(remaining) == 2, f"visible 2개만 남아야 함. 현재: {remaining}"
        assert "vis-sse-000" in remaining
        assert "vis-sse-001" in remaining
        for i in range(5):
            assert f"invis-sse-{i:03d}" not in remaining, \
                f"invisible runner(invis-sse-{i:03d})가 RECENT에 남아 있으면 안 됨"


# ---------------------------------------------------------------------------
# T3: 재현/통합 TC — invisible 오염 → SSE status 누락 재현 + 수정 검증
# ---------------------------------------------------------------------------

class TestInvisiblePollutionIntegration:

    def test_invisible_pollution_causes_empty_sse_status_integration(self):
        """T3(통합): invisible runner 25개 + visible 3개 → cleanup 후 _build_all_runners_status()에서 visible 3개 반환

        수정 전 시나리오 재현:
        - RECENT set에 invisible 25개(score=최근) + visible 3개(score=과거)
        - _cleanup_invisible_recent_runners() 없이 _build_all_runners_status() 호출 시
          set iteration 순서에 따라 visible runner가 MAX_RECENT_IN_SSE(20) 제한에 걸릴 수 있음
          (실제 버그: sorted set cap 없어 invisible이 수천 개로 불어나 성능 저하 + 오염)

        수정 후 검증:
        - _cleanup_invisible_recent_runners() 호출 → invisible 제거 → RECENT에 visible 3개만 남음
        - _build_all_runners_status() → visible 3개 모두 반환
        """
        from app.modules.dev_runner.services.event_service import (
            EventService,
            RECENT_RUNNERS_KEY as EVT_RECENT_KEY,
            RUNNER_KEY_PREFIX as EVT_PREFIX,
            ACTIVE_RUNNERS_KEY as EVT_ACTIVE_KEY,
        )
        fake = fakeredis.FakeRedis(decode_responses=True)

        # invisible runner 25개 (score=최근, RECENT set 오염 시뮬레이션)
        now = time.time()
        for i in range(25):
            rid = f"polluter-{i:03d}"
            fake.zadd(EVT_RECENT_KEY, {rid: now + i})
            fake.set(f"{EVT_PREFIX}:{rid}:status", "stopped")
            # trigger 미설정 = invisible

        # visible runner 3개 (score=과거 — old scores)
        for i in range(3):
            rid = f"real-user-{i:03d}"
            fake.zadd(EVT_RECENT_KEY, {rid: now - 3600 + i})  # 1시간 전
            fake.set(f"{EVT_PREFIX}:{rid}:status", "stopped")
            fake.set(f"{EVT_PREFIX}:{rid}:trigger", "user")
            fake.set(f"{EVT_PREFIX}:{rid}:plan_file", f"docs/plan/test-{i}.md")

        assert fake.zcard(EVT_RECENT_KEY) == 28

        # EventService에 fakeredis 주입
        svc = EventService.__new__(EventService)
        svc._sync = fake

        # 수정 후: _cleanup_invisible_recent_runners() 먼저 호출
        svc._cleanup_invisible_recent_runners()

        # cleanup 후 RECENT에 visible 3개만 남아야 함
        remaining = fake.zrange(EVT_RECENT_KEY, 0, -1)
        assert len(remaining) == 3, f"cleanup 후 visible 3개만 남아야 함. 현재: {remaining}"

        # _build_all_runners_status() 호출 (trigger=None 키 이슈 없이 가져와야 함)
        runners = svc._build_all_runners_status()

        # visible 3개 모두 포함되어야 함
        runner_ids_returned = {r["runner_id"] for r in runners if isinstance(r, dict)}
        for i in range(3):
            rid = f"real-user-{i:03d}"
            assert rid in runner_ids_returned, (
                f"visible runner({rid})가 _build_all_runners_status() 결과에 없음\n"
                f"반환된 runner_ids: {runner_ids_returned}"
            )
