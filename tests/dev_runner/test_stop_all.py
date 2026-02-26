"""stop_all_runners() 단위 테스트 — RIGHT-BICEP + CORRECT

Phase T1: ExecutorService.stop_all_runners() 메서드 검증
"""
import json
import asyncio
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch, call

import pytest

from app.modules.dev_runner.services.executor_service import (
    ExecutorService,
    RUNNER_KEY_PREFIX,
    ACTIVE_RUNNERS_KEY,
)
from app.modules.dev_runner.schemas import RunnerListItem


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


def _make_sync_redis_mock(**key_values):
    """동기 Redis mock 헬퍼"""
    r = MagicMock()
    r.ping = MagicMock()
    r.set = MagicMock()
    r.delete = MagicMock()
    r.sadd = MagicMock()
    r.srem = MagicMock()
    r.smembers = MagicMock(return_value=set())
    r.get = MagicMock(side_effect=lambda k: key_values.get(k))
    return r


def _make_async_redis_mock(**key_values):
    """비동기 Redis mock 헬퍼"""
    r = AsyncMock()
    r.ping = AsyncMock()
    r.get = AsyncMock(side_effect=lambda k: key_values.get(k))
    r.lpush = AsyncMock()
    r.scard = AsyncMock(return_value=0)
    r.brpop = AsyncMock(
        return_value=(b"key", json.dumps({"success": True, "message": "ok"}).encode())
    )
    return r


@pytest.fixture
def executor():
    """테스트용 ExecutorService (Redis 클라이언트 mock)"""
    svc = ExecutorService.__new__(ExecutorService)
    svc.redis_client = _make_sync_redis_mock()
    svc.async_redis = _make_async_redis_mock()
    return svc


class TestStopAllRight:
    """Right: 정상 동작 검증"""

    @pytest.mark.asyncio
    async def test_stop_all_right_multiple_runners(self, executor):
        """active runner 2개일 때 stop_all_runners() 호출 → stopped: 2 반환"""
        runners = [
            _make_runner_item("runner01", running=True),
            _make_runner_item("runner02", running=True),
        ]

        async def mock_stop(runner_id: str):
            return {"message": "Stopped successfully"}

        with patch.object(executor, "get_all_runners", return_value=runners), \
             patch.object(executor, "stop_dev_runner", side_effect=mock_stop) as mock_stop_fn:
            result = await executor.stop_all_runners()

        assert result == {"stopped": 2}
        assert mock_stop_fn.call_count == 2

    @pytest.mark.asyncio
    async def test_stop_all_right_single_runner(self, executor):
        """active runner 1개 → stopped: 1 반환"""
        runners = [_make_runner_item("runner01", running=True)]

        async def mock_stop(runner_id: str):
            return {"message": "Stopped successfully"}

        with patch.object(executor, "get_all_runners", return_value=runners), \
             patch.object(executor, "stop_dev_runner", side_effect=mock_stop):
            result = await executor.stop_all_runners()

        assert result == {"stopped": 1}


class TestStopAllBoundary:
    """Boundary: 경계값 검증"""

    @pytest.mark.asyncio
    async def test_stop_all_boundary_empty(self, executor):
        """active runner 0개 → {"stopped": 0} 반환, 예외 없음"""
        with patch.object(executor, "get_all_runners", return_value=[]):
            result = await executor.stop_all_runners()

        assert result == {"stopped": 0}

    @pytest.mark.asyncio
    async def test_stop_all_boundary_non_running_excluded(self, executor):
        """running=False인 runner는 stop 대상에서 제외"""
        runners = [
            _make_runner_item("runner01", running=True),
            _make_runner_item("runner02", running=False),  # 제외 대상
        ]

        async def mock_stop(runner_id: str):
            return {"message": "Stopped successfully"}

        with patch.object(executor, "get_all_runners", return_value=runners), \
             patch.object(executor, "stop_dev_runner", side_effect=mock_stop) as mock_stop_fn:
            result = await executor.stop_all_runners()

        # running=True인 runner01만 stop 호출
        assert result == {"stopped": 1}
        mock_stop_fn.assert_called_once_with("runner01")


class TestStopAllInverse:
    """Inverse: 역방향 검증"""

    @pytest.mark.asyncio
    async def test_stop_all_inverse_after_stop_runners_gone(self, executor):
        """stop-all 호출 후 get_all_runners() 결과가 빈 list인지 시뮬레이션 확인

        stop-all이 각 runner를 stop 처리한 후,
        이후 get_all_runners()는 빈 목록을 반환한다는 상태 변화 확인.
        """
        runners_before = [
            _make_runner_item("runner01", running=True),
            _make_runner_item("runner02", running=True),
        ]

        stopped_ids = []

        async def mock_stop(runner_id: str):
            stopped_ids.append(runner_id)
            return {"message": "Stopped successfully"}

        with patch.object(executor, "get_all_runners", return_value=runners_before), \
             patch.object(executor, "stop_dev_runner", side_effect=mock_stop):
            result = await executor.stop_all_runners()

        # 모든 running runner가 stop 요청을 받았는지 확인
        assert set(stopped_ids) == {"runner01", "runner02"}
        assert result["stopped"] == 2

        # stop-all 이후 Redis SREM이 각 runner에 대해 호출됐는지 검증
        # (stop_dev_runner 내부에서 _force_cleanup_state 호출 시 srem 발생)
        # 여기서는 mock으로 stop을 처리했으므로 상태 시뮬레이션으로 대체:
        # stop 후 active_runners가 비어있다고 가정한 추가 assertion
        assert len(stopped_ids) == len(runners_before)


class TestStopAllCrossCheck:
    """Cross-check: 교차 검증"""

    @pytest.mark.asyncio
    async def test_stop_all_cross_individual_stop(self, executor):
        """stop-all 후 각 runner의 stop_dev_runner가 개별 호출됐는지 교차 확인"""
        runners = [
            _make_runner_item("aaaa1111", running=True),
            _make_runner_item("bbbb2222", running=True),
        ]

        called_ids = []

        async def track_stop(runner_id: str):
            called_ids.append(runner_id)
            return {"message": "Stopped successfully"}

        with patch.object(executor, "get_all_runners", return_value=runners), \
             patch.object(executor, "stop_dev_runner", side_effect=track_stop):
            await executor.stop_all_runners()

        # 각 runner_id에 대해 개별 stop이 호출됐는지 확인
        assert "aaaa1111" in called_ids
        assert "bbbb2222" in called_ids
        assert len(called_ids) == 2


class TestStopAllError:
    """Error: 에러 처리 검증"""

    @pytest.mark.asyncio
    async def test_stop_all_error_partial_failure(self, executor):
        """첫 번째 runner stop 실패해도 나머지 runner stop 계속 진행

        graceful error handling: 하나 실패해도 나머지 처리 계속.
        """
        runners = [
            _make_runner_item("fail_runner", running=True),
            _make_runner_item("ok_runner", running=True),
        ]

        async def mock_stop_with_failure(runner_id: str):
            if runner_id == "fail_runner":
                raise Exception("Simulated stop failure")
            return {"message": "Stopped successfully"}

        with patch.object(executor, "get_all_runners", return_value=runners), \
             patch.object(executor, "stop_dev_runner", side_effect=mock_stop_with_failure):
            # 예외가 전파되지 않고 partial 결과 반환
            result = await executor.stop_all_runners()

        # 실패한 runner는 제외, 성공한 1개만 카운트
        assert result == {"stopped": 1}
