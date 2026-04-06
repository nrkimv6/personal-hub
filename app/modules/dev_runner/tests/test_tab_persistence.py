"""Dev Runner 탭 영속화 테스트 — Redis에 종료 runner 보존 구조 검증

TC 목록:
- test_stopped_runner_remains_in_recent: runner 종료 후 RECENT_RUNNERS_KEY에 존재하는지 확인
- test_get_all_runners_includes_recent: 종료된 runner가 get_all_runners() 목록에 포함되는지 확인
- test_dismiss_runner_removes_from_recent: dismiss 후 목록에서 사라지는지 확인
- test_old_runners_auto_cleaned: 24h 이상 된 runner가 get_all_runners() 호출 시 자동 정리되는지 확인
"""

import time
from unittest.mock import patch, MagicMock

import pytest
import fakeredis
import fakeredis.aioredis

from app.modules.dev_runner.services.executor_service import (
    executor_service,
    ACTIVE_RUNNERS_KEY,
    RECENT_RUNNERS_KEY,
    RUNNER_KEY_PREFIX,
    RECENT_RUNNERS_TTL,
)


@pytest.fixture(autouse=True)
def mock_executor_redis_sync():
    """executor_service의 redis_client와 async_redis를 fakeredis로 교체 (FakeServer 공유)
    + DB 쿼리(orphan 판별) mock — get_all_runners() 내부 SessionLocal 호출 격리
    """
    server = fakeredis.FakeServer()
    fake_sync = fakeredis.FakeRedis(server=server, decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None  # orphan 없음
    mock_session_local = MagicMock(return_value=mock_db)

    with patch.object(executor_service, 'redis_client', fake_sync), \
         patch.object(executor_service, 'async_redis', fake_async), \
         patch('app.database.SessionLocal', mock_session_local):
        yield fake_sync


class TestStoppedRunnerRemainsInRecent:
    """test_stopped_runner_remains_in_recent — runner 종료 후 RECENT_RUNNERS_KEY에 존재 확인"""

    @pytest.mark.asyncio
    async def test_stopped_runner_remains_in_recent(self, mock_executor_redis_sync):
        """_force_cleanup_state() 후 runner가 RECENT_RUNNERS_KEY에 보존되는지 확인"""
        fake = mock_executor_redis_sync
        rid = "test-runner-abc1"

        # runner 활성화 상태 설정
        fake.sadd(ACTIVE_RUNNERS_KEY, rid)
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file", "test.md")
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", "12345")

        # 강제 정리 (runner 종료 시뮬레이션)
        await executor_service._force_cleanup_state(rid)

        # ACTIVE_RUNNERS_KEY에서 제거됐는지 확인
        assert not fake.sismember(ACTIVE_RUNNERS_KEY, rid)

        # RECENT_RUNNERS_KEY에 보존됐는지 확인
        recent_ids = fake.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert rid in recent_ids

        # status가 "stopped"으로 변경됐는지 확인
        status = fake.get(f"{RUNNER_KEY_PREFIX}:{rid}:status")
        assert status == "stopped"

    @pytest.mark.asyncio
    async def test_force_cleanup_all_runners_remain_in_recent(self, mock_executor_redis_sync):
        """전체 정리 시 모든 runner가 RECENT_RUNNERS_KEY에 보존되는지 확인"""
        fake = mock_executor_redis_sync
        rids = ["runner-001", "runner-002"]

        for rid in rids:
            fake.sadd(ACTIVE_RUNNERS_KEY, rid)
            fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")

        # runner_id 없이 호출 = 전체 정리
        await executor_service._force_cleanup_state()

        recent_ids = fake.zrange(RECENT_RUNNERS_KEY, 0, -1)
        for rid in rids:
            assert rid in recent_ids


class TestGetAllRunnersIncludesRecent:
    """test_get_all_runners_includes_recent — 종료된 runner가 목록에 포함되는지 확인"""

    @pytest.mark.asyncio
    async def test_get_all_runners_includes_recent(self, mock_executor_redis_sync):
        """RECENT_RUNNERS_KEY에 있는 종료 runner가 get_all_runners()에 포함되는지 확인"""
        fake = mock_executor_redis_sync
        rid = "test-runner-def2"

        # 종료된 runner 상태 세팅 (ACTIVE가 아닌 RECENT에만 존재)
        fake.zadd(RECENT_RUNNERS_KEY, {rid: time.time()})
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file", "stopped-plan.md")

        runners = await executor_service.get_all_runners()
        runner_ids = [r.runner_id for r in runners]

        assert rid in runner_ids
        # running=False 확인
        runner = next(r for r in runners if r.runner_id == rid)
        assert runner.running is False

    @pytest.mark.asyncio
    async def test_get_all_runners_includes_both_active_and_recent(self, mock_executor_redis_sync):
        """활성 runner + 최근 종료 runner 모두 포함되는지 확인"""
        fake = mock_executor_redis_sync
        active_rid = "active-runner-001"
        stopped_rid = "stopped-runner-001"

        # 활성 runner
        fake.sadd(ACTIVE_RUNNERS_KEY, active_rid)
        fake.set(f"{RUNNER_KEY_PREFIX}:{active_rid}:status", "running")

        # 종료 runner
        fake.zadd(RECENT_RUNNERS_KEY, {stopped_rid: time.time()})
        fake.set(f"{RUNNER_KEY_PREFIX}:{stopped_rid}:status", "stopped")

        runners = await executor_service.get_all_runners()
        runner_ids = [r.runner_id for r in runners]

        assert active_rid in runner_ids
        assert stopped_rid in runner_ids


class TestDismissRunnerRemovesFromRecent:
    """test_dismiss_runner_removes_from_recent — dismiss 후 목록에서 사라지는지 확인"""

    @pytest.mark.asyncio
    async def test_dismiss_runner_removes_from_recent(self, mock_executor_redis_sync):
        """dismiss_runner() 후 RECENT_RUNNERS_KEY에서 제거 확인"""
        fake = mock_executor_redis_sync
        rid = "test-runner-ghi3"

        fake.zadd(RECENT_RUNNERS_KEY, {rid: time.time()})
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file", "old-plan.md")

        result = await executor_service.dismiss_runner(rid)

        assert result is True
        # RECENT_RUNNERS_KEY에서 제거됐는지 확인
        recent_ids = fake.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert rid not in recent_ids
        # per-runner 키도 삭제됐는지 확인
        assert fake.get(f"{RUNNER_KEY_PREFIX}:{rid}:status") is None
        assert fake.get(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file") is None

    @pytest.mark.asyncio
    async def test_dismiss_removes_from_get_all_runners(self, mock_executor_redis_sync):
        """dismiss 후 get_all_runners()에서 사라지는지 확인"""
        fake = mock_executor_redis_sync
        rid = "test-runner-jkl4"

        fake.zadd(RECENT_RUNNERS_KEY, {rid: time.time()})
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")

        # dismiss 전 목록에 있는지 확인
        runners_before = await executor_service.get_all_runners()
        assert rid in [r.runner_id for r in runners_before]

        await executor_service.dismiss_runner(rid)

        # dismiss 후 목록에서 사라졌는지 확인
        runners_after = await executor_service.get_all_runners()
        assert rid not in [r.runner_id for r in runners_after]


class TestOldRunnersAutoCleaned:
    """test_old_runners_auto_cleaned — 24h 이상 된 runner가 자동 정리되는지 확인"""

    @pytest.mark.asyncio
    async def test_old_runners_auto_cleaned(self, mock_executor_redis_sync):
        """get_all_runners() 호출 시 24h 이상 된 runner가 RECENT_RUNNERS_KEY에서 자동 정리"""
        fake = mock_executor_redis_sync
        old_rid = "old-runner-mno5"
        recent_rid = "recent-runner-pqr6"

        # 25시간 전에 종료된 runner (자동 정리 대상)
        old_ts = time.time() - (RECENT_RUNNERS_TTL + 3600)  # 25시간 전
        fake.zadd(RECENT_RUNNERS_KEY, {old_rid: old_ts})
        fake.set(f"{RUNNER_KEY_PREFIX}:{old_rid}:status", "stopped")

        # 30분 전에 종료된 runner (보존 대상, TTL 내)
        recent_ts = time.time() - 1800  # 30분 전
        fake.zadd(RECENT_RUNNERS_KEY, {recent_rid: recent_ts})
        fake.set(f"{RUNNER_KEY_PREFIX}:{recent_rid}:status", "stopped")

        runners = await executor_service.get_all_runners()
        runner_ids = [r.runner_id for r in runners]

        # 오래된 runner는 목록에서 사라져야 함
        assert old_rid not in runner_ids
        # 최근 runner는 목록에 있어야 함
        assert recent_rid in runner_ids

    @pytest.mark.asyncio
    async def test_old_runners_removed_from_recent_key(self, mock_executor_redis_sync):
        """get_all_runners() 후 RECENT_RUNNERS_KEY에서도 실제로 제거됐는지 확인"""
        fake = mock_executor_redis_sync
        old_rid = "stale-runner-stu7"

        old_ts = time.time() - (RECENT_RUNNERS_TTL + 7200)  # 26시간 전
        fake.zadd(RECENT_RUNNERS_KEY, {old_rid: old_ts})
        fake.set(f"{RUNNER_KEY_PREFIX}:{old_rid}:status", "stopped")

        await executor_service.get_all_runners()

        # RECENT_RUNNERS_KEY에서도 제거됐는지 확인
        recent_ids = fake.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert old_rid not in recent_ids


class TestCleanupStaleKeepsStoppedRunner:
    """cleanup-stale 호출 시 TTL 내 stopped runner 보존 확인"""

    @pytest.mark.asyncio
    async def test_cleanup_stale_keeps_stopped_tab_within_ttl(self, mock_executor_redis_sync):
        fake = mock_executor_redis_sync
        rid = "stopped-cleanup-keep-001"

        fake.zadd(RECENT_RUNNERS_KEY, {rid: time.time()})
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
        fake.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file", "docs/plan/missing-plan.md")

        result = await executor_service.cleanup_stale_runners()
        assert result["cleaned_recent"] == 0
        assert result.get("preserved_recent", 0) == 1

        runners = await executor_service.get_all_runners()
        assert rid in [r.runner_id for r in runners]


class TestConnectionError503:
    """ConnectionError → 503 반환 검증 (Phase 3 수정)"""

    @pytest.mark.asyncio
    async def test_get_all_runners_redis_connection_error_raises(self, mock_executor_redis_sync):
        """E: async_redis.smembers에서 ConnectionError → get_all_runners()가 예외 전파 (빈 리스트 반환 안 함)"""
        import redis
        with patch.object(executor_service.async_redis, "smembers", side_effect=redis.ConnectionError("test")):
            with pytest.raises(redis.ConnectionError):
                await executor_service.get_all_runners()

    @pytest.mark.asyncio
    async def test_list_runners_503_on_connection_error(self):
        """E: get_all_runners()가 ConnectionError raise → /runners 엔드포인트 503 응답"""
        import redis
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service.get_all_runners",
            side_effect=redis.ConnectionError("test"),
        ):
            response = client.get("/api/v1/dev-runner/runners")

        assert response.status_code == 503, (
            f"ConnectionError 시 503이 아닌 {response.status_code} 반환됨\n"
            f"응답: {response.text}"
        )


class TestT4EndpointVisibility:
    """Phase T4: HTTP 엔드포인트 통합 — trigger='user' 러너 가시성 + 503 확인"""

    @pytest.mark.asyncio
    async def test_runners_endpoint_after_merge_restart_visible(self, mock_executor_redis_sync):
        """T4: trigger='user' 러너가 ACTIVE에 등록된 후 GET /runners 응답에 표시됨 확인"""
        from fastapi.testclient import TestClient
        from app.main import app

        runner_id = "tc-t4-merge-restart-001"
        # fakeredis에 trigger='user' 러너 등록 (merge 후 재시작 시나리오)
        mock_executor_redis_sync.sadd(ACTIVE_RUNNERS_KEY, runner_id)
        mock_executor_redis_sync.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        mock_executor_redis_sync.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        mock_executor_redis_sync.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/dev-runner/runners")

        assert response.status_code == 200, f"예상 200, 실제 {response.status_code}: {response.text}"
        runners = response.json()
        runner_ids = [r["runner_id"] for r in runners]
        assert runner_id in runner_ids, (
            f"trigger='user' 러너({runner_id})가 /runners 응답에 없음\n"
            f"  응답 runner_ids: {runner_ids}\n"
            f"  이 실패는 visibility 필터링 회귀를 의미합니다."
        )

    @pytest.mark.asyncio
    async def test_runners_endpoint_503_on_redis_error(self, mock_executor_redis_sync):
        """T4: async_redis ConnectionError → GET /runners → 503 응답"""
        import redis
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)

        with patch.object(executor_service.async_redis, "smembers", side_effect=redis.ConnectionError("t4-test")):
            response = client.get("/api/v1/dev-runner/runners")

        assert response.status_code == 503, (
            f"async_redis ConnectionError 시 503이 아닌 {response.status_code} 반환됨\n"
            f"응답: {response.text}"
        )
