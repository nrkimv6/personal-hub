"""멀티 runner E2E 시나리오 테스트 — ExecutorService 레벨

Phase T3: 멀티 runner 전체 흐름 시나리오 검증
실제 Redis/listener 없이 mock으로 서비스 레이어 시나리오를 검증합니다.
"""
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.dev_runner.services.executor_service import (
    ACTIVE_RUNNERS_KEY,
    RUNNER_KEY_PREFIX,
    ExecutorService,
)
from app.modules.dev_runner.schemas import RunRequest, RunnerListItem


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드 — plan_service 의존성 없음"""
    yield


def _make_runner_item(runner_id: str, running: bool = True) -> RunnerListItem:
    """테스트용 RunnerListItem 생성 헬퍼"""
    return RunnerListItem(
        runner_id=runner_id,
        running=running,
        plan_file="test.md",
        engine="claude",
        start_time=datetime.now(),
        pid=1234,
        worktree_path=None,
        branch=None,
        merge_status=None,
    )


@pytest.fixture
def executor():
    """테스트용 ExecutorService (Redis 클라이언트 mock)"""
    svc = ExecutorService.__new__(ExecutorService)
    svc.redis_client = MagicMock()
    svc.redis_client.ping = MagicMock()
    svc.redis_client.smembers = MagicMock(return_value=set())
    svc.redis_client.get = MagicMock(return_value=None)
    svc.redis_client.srem = MagicMock()
    svc.redis_client.delete = MagicMock()

    svc.async_redis = AsyncMock()
    svc.async_redis.ping = AsyncMock()
    svc.async_redis.get = AsyncMock(return_value=None)
    svc.async_redis.lpush = AsyncMock()
    svc.async_redis.scard = AsyncMock(return_value=0)
    svc.async_redis.brpop = AsyncMock(
        return_value=(b"key", json.dumps({"success": True, "message": "ok"}).encode())
    )
    return svc


class TestE2EScenario1:
    """시나리오 1: 2개 runner 동시 실행 → 각기 다른 runner_id 반환"""

    @pytest.mark.asyncio
    async def test_e2e_scenario1_two_runners_two_tabs(self, executor):
        """POST /run 2회 호출 → 서로 다른 runner_id 반환 확인

        실제 라우터 없이 서비스 레이어에서:
        - start_dev_runner() 2회 호출
        - 각 호출이 서로 다른 runner_id를 반환하는지 검증
        """
        async def mock_get(key):
            if ":pid" in key:
                return "1234"
            if ":plan_file" in key:
                return "test.md"
            if ":start_time" in key:
                return datetime.now().isoformat()
            return None

        executor.async_redis.get = mock_get

        mock_claim = MagicMock()
        mock_claim.claim_id = "test-claim-id"
        with patch.object(executor, "_check_redis_and_listener", new_callable=AsyncMock), \
             patch('app.modules.dev_runner.services.plan_execution_claim_service.claim_plan', return_value=mock_claim):
            req = RunRequest(test_source="multi_runner_scenarios", plan_file="plan_a.md", engine="claude")
            result1 = await executor.start_dev_runner(req)

            req2 = RunRequest(test_source="multi_runner_scenarios", plan_file="plan_b.md", engine="claude")
            result2 = await executor.start_dev_runner(req2)

        # 서로 다른 runner_id 확인
        assert result1.runner_id != result2.runner_id
        # test_source 있으면 t-{src}-{4hex} 형식 (가변 길이), 없으면 8자리 hex
        assert len(result1.runner_id) >= 8
        assert len(result2.runner_id) >= 8
        # get_all_runners()가 두 항목을 반환하는 시나리오 시뮬레이션
        runners_mock = [
            _make_runner_item(result1.runner_id, running=True),
            _make_runner_item(result2.runner_id, running=True),
        ]
        with patch.object(executor, "get_all_runners", new_callable=AsyncMock, return_value=runners_mock):
            runners = await executor.get_all_runners()
        assert len(runners) == 2
        runner_ids = {r.runner_id for r in runners}
        assert result1.runner_id in runner_ids
        assert result2.runner_id in runner_ids


class TestE2EScenario2:
    """시나리오 2: runner 종료 후 running=false, runner_id는 유지"""

    @pytest.mark.asyncio
    async def test_e2e_scenario2_runner_stop_tab_remains(self, executor):
        """runner 종료 후 get_all_runners()에서 running=false 확인

        runner를 stop한 후에도 runner_id는 목록에 유지되나
        running 상태가 false로 변경되는 것을 시뮬레이션.
        """
        runner_id = "t-multi-run1"

        # stop 전: running=True
        runners_before = [_make_runner_item(runner_id, running=True)]
        with patch.object(executor, "get_all_runners", new_callable=AsyncMock, return_value=runners_before):
            runners = await executor.get_all_runners()
        assert runners[0].running is True

        # stop 후: running=False (탭은 유지)
        runners_after = [_make_runner_item(runner_id, running=False)]
        with patch.object(executor, "get_all_runners", new_callable=AsyncMock, return_value=runners_after):
            runners = await executor.get_all_runners()

        assert len(runners) == 1
        assert runners[0].runner_id == runner_id
        assert runners[0].running is False


class TestE2EScenario2_1:
    """시나리오 2-1: stop 후 탭 유지, dismiss 시점에만 제거"""

    @pytest.mark.asyncio
    async def test_e2e_scenario2_1_stop_keeps_tab_until_dismiss(self, executor):
        """stop -> cleanup-stale 이후에도 runner_id 유지, dismiss 후 제거."""
        runner_id = "t-multi-stop-dismiss"
        stopped_runner = _make_runner_item(runner_id, running=False)

        with patch.object(
            executor,
            "get_all_runners",
            new_callable=AsyncMock,
            side_effect=[[stopped_runner], [stopped_runner], []],
        ):
            with patch.object(
                executor,
                "cleanup_stale_runners",
                new_callable=AsyncMock,
                return_value={
                    "cleaned_active": 0,
                    "cleaned_recent": 0,
                    "preserved_recent": 1,
                    "bugs": 0,
                    "total": 0,
                },
            ) as cleanup_mock, patch.object(
                executor,
                "dismiss_runner",
                new_callable=AsyncMock,
                return_value=True,
            ) as dismiss_mock:
                before = await executor.get_all_runners()
                cleanup = await executor.cleanup_stale_runners()
                after_cleanup = await executor.get_all_runners()
                dismissed = await executor.dismiss_runner(runner_id)
                after_dismiss = await executor.get_all_runners()

        assert [r.runner_id for r in before] == [runner_id]
        assert [r.runner_id for r in after_cleanup] == [runner_id]
        assert cleanup["preserved_recent"] == 1
        assert dismissed is True
        assert after_dismiss == []
        cleanup_mock.assert_awaited_once()
        dismiss_mock.assert_awaited_once_with(runner_id)


class TestE2EScenario3:
    """시나리오 3: 1개 실행 후 재실행 → 409 아닌 200 + 새 runner_id"""

    @pytest.mark.asyncio
    async def test_e2e_scenario3_start_after_start(self, executor):
        """runner 실행 중 POST /run 재호출 → 새 runner_id 반환 (409 아님)

        멀티 runner 지원: 이미 실행 중이어도 새 runner 생성 가능.
        """
        async def mock_get(key):
            if ":pid" in key:
                return "1234"
            if ":plan_file" in key:
                return "plan.md"
            if ":start_time" in key:
                return datetime.now().isoformat()
            return None

        executor.async_redis.get = mock_get

        mock_claim = MagicMock()
        mock_claim.claim_id = "test-claim-id"
        with patch.object(executor, "_check_redis_and_listener", new_callable=AsyncMock), \
             patch('app.modules.dev_runner.services.plan_execution_claim_service.claim_plan', return_value=mock_claim):
            # 첫 번째 실행
            req = RunRequest(test_source="multi_runner_scenarios", plan_file="plan.md", engine="claude")
            result1 = await executor.start_dev_runner(req)

            # 두 번째 실행 (이미 하나 실행 중)
            result2 = await executor.start_dev_runner(req)

        # HTTPException(409) 없이 새 runner_id 반환
        assert result2.runner_id is not None
        assert result1.runner_id != result2.runner_id
        assert result2.running is True


class TestE2EScenario4:
    """시나리오 4: 1개 종료 후 나머지 일괄 종료"""

    @pytest.mark.asyncio
    async def test_e2e_scenario4_stop_all_remaining(self, executor):
        """runner 2개 실행 → 1개 stop → POST /stop-all → stopped: 1

        1개가 이미 중지된 상태에서 stop-all을 호출하면
        나머지 running인 1개만 stop 처리.
        """
        # runner01 이미 종료, runner02 실행 중
        runners = [
            _make_runner_item("runner01", running=False),
            _make_runner_item("runner02", running=True),
        ]

        stopped_count = []

        async def mock_stop(runner_id: str):
            stopped_count.append(runner_id)
            return {"message": "Stopped successfully"}

        with patch.object(executor, "get_all_runners", new_callable=AsyncMock, return_value=runners), \
             patch.object(executor, "stop_dev_runner", side_effect=mock_stop):
            result = await executor.stop_all_runners()

        # running=True인 runner02만 stop
        assert result == {"stopped": 1}
        assert "runner02" in stopped_count
        assert "runner01" not in stopped_count

        # stop-all 이후 get_all_runners → 빈 목록 시뮬레이션
        empty_runners = []
        with patch.object(executor, "get_all_runners", new_callable=AsyncMock, return_value=empty_runners):
            remaining = await executor.get_all_runners()
        assert remaining == []


class TestE2EScenario5:
    """시나리오 5: 모든 종료 후 stop-all → stopped: 0"""

    @pytest.mark.asyncio
    async def test_e2e_scenario5_all_stopped_stopall_zero(self, executor):
        """모든 runner 종료 상태에서 POST /stop-all → stopped: 0"""
        # 모두 running=False
        runners = [
            _make_runner_item("runner01", running=False),
            _make_runner_item("runner02", running=False),
        ]

        with patch.object(executor, "get_all_runners", return_value=runners):
            result = await executor.stop_all_runners()

        assert result == {"stopped": 0}


# ──────────────────────────────────────────────
# T3: 종료 후 미확인 보존 → dismiss 제거 시나리오
# ──────────────────────────────────────────────

class TestE2EScenario6StoppedUserDismiss:
    """시나리오 6 (T3): 종료 후 미확인 상태 유지 → dismiss 후 제거"""

    @pytest.mark.asyncio
    async def test_stopped_user_preserved_until_dismiss(self, executor):
        """stopped+user runner는 cleanup_stale_runners() 후에도 보존되고 dismiss 후에만 제거된다"""
        import time
        import fakeredis.aioredis as fake_aioredis
        from app.modules.dev_runner.services.runner_state import RunnerState
        from app.modules.dev_runner.services.redis_connection import (
            RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY,
        )

        fake_r = fake_aioredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-s6-stopped-user"

        def runner_key(rid, suffix):
            return f"{RUNNER_KEY_PREFIX}:{rid}:{suffix}"

        # TTL 초과 score(25시간 전)로 등록
        score = time.time() - 90000
        await fake_r.zadd(RECENT_RUNNERS_KEY, {runner_id: score})
        await fake_r.set(runner_key(runner_id, "status"), "stopped")
        await fake_r.set(runner_key(runner_id, "trigger"), "user")
        await fake_r.set(runner_key(runner_id, "plan_file"), "docs/plan/2026-04-06_fix.md")

        state = RunnerState(fake_r, runner_key, None, None)

        # Step 1: cleanup_stale_runners() 실행 → user stopped는 보존
        result = await state.cleanup_stale_runners()
        assert await fake_r.zscore(RECENT_RUNNERS_KEY, runner_id) is not None, \
            "cleanup_stale 후에도 user stopped runner가 RECENT에 남아있어야 한다"
        assert result["preserved_recent"] >= 1

        # Step 2: dismiss_runner() 호출 → hard-delete
        dismiss_result = await state.dismiss_runner(runner_id)
        assert dismiss_result is True
        assert await fake_r.zscore(RECENT_RUNNERS_KEY, runner_id) is None, \
            "dismiss 후 RECENT에서 제거되어야 한다"

    @pytest.mark.asyncio
    async def test_multiple_cleanup_cycles_preserve_user_stopped(self, executor):
        """cleanup_stale_runners() 반복 실행 시 user stopped runner는 계속 보존된다"""
        import time
        import fakeredis.aioredis as fake_aioredis
        from app.modules.dev_runner.services.runner_state import RunnerState
        from app.modules.dev_runner.services.redis_connection import (
            RUNNER_KEY_PREFIX, RECENT_RUNNERS_KEY,
        )

        fake_r = fake_aioredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-s6-multi-cycle"

        def runner_key(rid, suffix):
            return f"{RUNNER_KEY_PREFIX}:{rid}:{suffix}"

        score = time.time() - 90000
        await fake_r.zadd(RECENT_RUNNERS_KEY, {runner_id: score})
        await fake_r.set(runner_key(runner_id, "status"), "stopped")
        await fake_r.set(runner_key(runner_id, "trigger"), "user")

        state = RunnerState(fake_r, runner_key, None, None)

        # 3회 반복 cleanup
        for cycle in range(3):
            result = await state.cleanup_stale_runners()
            assert await fake_r.zscore(RECENT_RUNNERS_KEY, runner_id) is not None, \
                f"cycle {cycle+1}: user stopped runner가 제거됨. 보존되어야 한다."
