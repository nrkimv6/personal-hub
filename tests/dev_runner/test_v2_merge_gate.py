"""
TC: v2 merge gate (handle_merge_stage 내 lock acquire/release) 단위 테스트

Phase T1 TC:
- test_v2_gate_lock_timeout_returns_failed_E: timeout → FAILED + execute_merge 미호출 (ERROR)
- test_v2_gate_lock_acquired_before_merge_R: lock acquire가 execute_merge보다 먼저 (RIGHT)
- test_v2_gate_lock_released_on_success_R: 성공 시 finally에서 release (RIGHT)
- test_v2_gate_lock_released_on_exception_E: 예외 발생 시도 finally에서 release (ERROR)
- test_v2_gate_no_redis_skips_lock_B: redis=None → lock 스킵, execute_merge 실행 (BOUNDARY)
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from tests.dev_runner.conftest import assert_no_magicmock_leak, make_strict_redis_mock

# wtools plan-runner 경로 추가
_WTOOLS_CORE = Path(__file__).parents[4] / "service" / "wtools" / "common" / "tools" / "plan-runner"
if str(_WTOOLS_CORE) not in sys.path:
    sys.path.insert(0, str(_WTOOLS_CORE))

import plan_runner.core.merge_stage as _ms
from plan_runner.core.merge_stage import handle_merge_stage, StageResult


@pytest.fixture
def project_dir(tmp_path):
    return tmp_path


def _strict_redis_mock() -> MagicMock:
    return make_strict_redis_mock()


def _run(coro):
    return asyncio.run(coro)


class TestV2MergeGate:
    def test_v2_gate_strict_redis_default_none_B(self):
        """B(Boundary): strict helper 기본값 누출이 lock 분기를 오염시키지 않는다."""
        mock_redis = _strict_redis_mock()
        value = mock_redis.get("plan-runner:runners:strict-check:merge_requested")
        assert_no_magicmock_leak(value, "redis.get")
        assert value is None

    def test_v2_gate_lock_timeout_returns_failed_E(self, project_dir):
        """E(Error): lock acquire timeout → StageResult(FAILED) + execute_merge 미호출"""
        mock_redis = _strict_redis_mock()

        with patch.object(_ms, "_ml_acquire", return_value=False), \
             patch.object(_ms, "execute_merge") as mock_exec, \
             patch("plan_runner.core.merge_stage._redis_mod") as mock_redis_mod:
            mock_redis_mod.Redis.return_value = mock_redis
            result = _run(handle_merge_stage(
                project_dir=project_dir,
                runner_id="test-runner",
                python_path="python",
                branch="impl/test",
                worktree_path=project_dir / "wt",
                plan_file="plan.md",
            ))

        assert result.status == "FAILED"
        assert "timeout" in result.error_summary.lower() or "lock" in result.error_summary.lower()
        mock_exec.assert_not_called()

    def test_v2_gate_lock_acquired_before_merge_R(self, project_dir):
        """R(Right): lock acquire 호출이 execute_merge 호출보다 먼저 발생"""
        call_order = []
        mock_redis = _strict_redis_mock()

        def mock_acquire(*args, **kwargs):
            call_order.append("acquire")
            return True

        async def mock_exec(*args, **kwargs):
            call_order.append("execute_merge")
            from plan_runner.core.merge_stage import PostMergeResult
            return PostMergeResult(success=True, merged=True, conflict=False, test_passed=True, message="OK")

        async def mock_tests(*args, **kwargs):
            from plan_runner.core.merge_stage import PostMergeResult
            return PostMergeResult(success=True, merged=True, conflict=False, test_passed=True, message="OK", fix_attempts=0)

        with patch.object(_ms, "_ml_acquire", side_effect=mock_acquire), \
             patch.object(_ms, "_ml_release"), \
             patch.object(_ms, "execute_merge", side_effect=mock_exec), \
             patch.object(_ms, "run_post_merge_tests", side_effect=mock_tests), \
             patch.object(_ms, "run_done", return_value=True), \
             patch("plan_runner.core.merge_stage._redis_mod") as mock_redis_mod:
            mock_redis_mod.Redis.return_value = mock_redis
            _run(handle_merge_stage(
                project_dir=project_dir,
                runner_id="test-runner",
                python_path="python",
                branch="impl/test",
                worktree_path=project_dir / "wt",
                plan_file="plan.md",
            ))

        assert call_order.index("acquire") < call_order.index("execute_merge")

    def test_v2_gate_lock_released_on_success_R(self, project_dir):
        """R(Right): 성공 시나리오 → finally 블록에서 _ml_release 호출"""
        mock_redis = _strict_redis_mock()

        async def mock_exec(*args, **kwargs):
            from plan_runner.core.merge_stage import PostMergeResult
            return PostMergeResult(success=True, merged=True, conflict=False, test_passed=True, message="OK")

        async def mock_tests(*args, **kwargs):
            from plan_runner.core.merge_stage import PostMergeResult
            return PostMergeResult(success=True, merged=True, conflict=False, test_passed=True, message="OK", fix_attempts=0)

        with patch.object(_ms, "_ml_acquire", return_value=True), \
             patch.object(_ms, "_ml_release") as mock_release, \
             patch.object(_ms, "execute_merge", side_effect=mock_exec), \
             patch.object(_ms, "run_post_merge_tests", side_effect=mock_tests), \
             patch.object(_ms, "run_done", return_value=True), \
             patch("plan_runner.core.merge_stage._redis_mod") as mock_redis_mod:
            mock_redis_mod.Redis.return_value = mock_redis
            _run(handle_merge_stage(
                project_dir=project_dir,
                runner_id="test-runner",
                python_path="python",
                branch="impl/test",
                worktree_path=project_dir / "wt",
                plan_file="plan.md",
            ))

        mock_release.assert_called_once()

    def test_v2_gate_lock_released_on_exception_E(self, project_dir):
        """E(Error): execute_merge 예외 발생 → finally에서 _ml_release 여전히 호출"""
        mock_redis = _strict_redis_mock()

        async def mock_exec_raises(*args, **kwargs):
            raise RuntimeError("merge exploded")

        with patch.object(_ms, "_ml_acquire", return_value=True), \
             patch.object(_ms, "_ml_release") as mock_release, \
             patch.object(_ms, "execute_merge", side_effect=mock_exec_raises), \
             patch("plan_runner.core.merge_stage._redis_mod") as mock_redis_mod:
            mock_redis_mod.Redis.return_value = mock_redis
            result = _run(handle_merge_stage(
                project_dir=project_dir,
                runner_id="test-runner",
                python_path="python",
                branch="impl/test",
                worktree_path=project_dir / "wt",
                plan_file="plan.md",
            ))

        assert result.status == "FAILED"
        mock_release.assert_called_once()

    def test_v2_gate_no_redis_skips_lock_B(self, project_dir):
        """B(Boundary): redis_client=None (연결 실패) → lock acquire 스킵, execute_merge 정상 실행"""
        call_order = []

        async def mock_exec(*args, **kwargs):
            call_order.append("execute_merge")
            from plan_runner.core.merge_stage import PostMergeResult
            return PostMergeResult(success=True, merged=True, conflict=False, test_passed=True, message="OK")

        async def mock_tests(*args, **kwargs):
            from plan_runner.core.merge_stage import PostMergeResult
            return PostMergeResult(success=True, merged=True, conflict=False, test_passed=True, message="OK", fix_attempts=0)

        with patch.object(_ms, "_ml_acquire") as mock_acquire, \
             patch.object(_ms, "execute_merge", side_effect=mock_exec), \
             patch.object(_ms, "run_post_merge_tests", side_effect=mock_tests), \
             patch.object(_ms, "run_done", return_value=True), \
             patch("plan_runner.core.merge_stage._redis_mod", None):
            result = _run(handle_merge_stage(
                project_dir=project_dir,
                runner_id="test-runner",
                python_path="python",
                branch="impl/test",
                worktree_path=project_dir / "wt",
                plan_file="plan.md",
            ))

        mock_acquire.assert_not_called()
        assert "execute_merge" in call_order
        assert result.status == "SUCCESS"
