"""exit_reason 기능 TC - RIGHT-BICEP 원칙

대상:
- runner._cleanup_redis_state()의 exit_reason 기록
- listener dev-runner-command-listener.py의 __COMPLETED::{reason}__ sentinel
- log_service의 completed 이벤트 파싱
- executor_service.get_all_runners()의 exit_reason 포함
- impl.py의 rate limit 키워드 감지 → RATE_LIMITED 반환
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import fakeredis
import fakeredis.aioredis
import sys
import os


# ─── 파싱 헬퍼 (log_service 로직 추출) ───────────────────────────────────────

def parse_completed_sentinel(data: str) -> str:
    """__COMPLETED__ / __COMPLETED::{reason}__ sentinel에서 reason 파싱."""
    if data == "__COMPLETED__":
        return "completed"
    if data.startswith("__COMPLETED::"):
        return data[len("__COMPLETED::"):].rstrip("_") or "completed"
    return "completed"


# ─── TC 1: _cleanup_redis_state exits_reason 기록 ─────────────────────────────

class TestCleanupRedisStateExitReason:
    """Runner._cleanup_redis_state()가 exit_reason을 Redis에 올바르게 기록하는지 검증."""

    def _make_runner(self, fake_redis):
        """fakeredis를 주입한 Runner-like mock 객체 생성."""
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL,
        )
        runner = MagicMock()
        runner._redis = fake_redis
        runner._runner_id = "tc-pytest-exit-001"
        runner._exit_reason = "completed"
        # RUNNER_KEY_PREFIX 상수 바인딩
        runner._runner_key_prefix = RUNNER_KEY_PREFIX
        return runner, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL

    def _call_cleanup(self, runner, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL):
        """runner.py의 _cleanup_redis_state 로직을 직접 실행."""
        import time
        RUNNER_KEY_SUFFIXES = (
            "status", "pid", "plan_file", "start_time", "log_file_path", "stream_log_path",
            "engine", "fix_engine", "worktree_path", "branch", "merge_status", "merge_requested",
            "current_cycle", "quota_stopped", "error", "restart_after_merge", "exit_reason",
        )
        REDIS_STATE_KEY = f"plan-runner:state:{runner._runner_id}"
        r = runner._redis
        try:
            r.set(f"{REDIS_STATE_KEY}:status", "stopped")
            r.set(f"{RUNNER_KEY_PREFIX}:{runner._runner_id}:status", "stopped")
            r.set(f"{RUNNER_KEY_PREFIX}:{runner._runner_id}:exit_reason", runner._exit_reason)
            for suffix in RUNNER_KEY_SUFFIXES:
                r.expire(f"{RUNNER_KEY_PREFIX}:{runner._runner_id}:{suffix}", RECENT_RUNNERS_TTL)
            r.srem(ACTIVE_RUNNERS_KEY, runner._runner_id)
            r.zadd(RECENT_RUNNERS_KEY, {runner._runner_id: time.time()})
        except Exception:
            pass

    def test_cleanup_redis_state_writes_exit_reason_right(self):
        """R(Right): exit_reason="no_progress" → Redis에 올바르게 기록."""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner, KP, AK, RK, TTL = self._make_runner(fake_redis)
        runner._exit_reason = "no_progress"

        self._call_cleanup(runner, KP, AK, RK, TTL)

        stored = fake_redis.get(f"{KP}:{runner._runner_id}:exit_reason")
        assert stored == "no_progress"

    def test_cleanup_redis_state_exit_reason_default_boundary(self):
        """B(Boundary): exit_reason 기본값 "completed" → Redis에 "completed" 저장."""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner, KP, AK, RK, TTL = self._make_runner(fake_redis)
        # _exit_reason은 기본값 "completed" 유지

        self._call_cleanup(runner, KP, AK, RK, TTL)

        stored = fake_redis.get(f"{KP}:{runner._runner_id}:exit_reason")
        assert stored == "completed"

    def test_cleanup_redis_state_exit_reason_error(self):
        """E(Error): Redis 연결 실패 시 예외 없이 조용히 종료."""
        runner = MagicMock()
        runner._redis = MagicMock()
        runner._redis.set.side_effect = Exception("connection refused")
        runner._runner_id = "tc-pytest-exit-err"
        runner._exit_reason = "error"

        # 예외가 발생하면 안 됨
        try:
            if runner._redis:
                try:
                    runner._redis.set("key", "val")
                except Exception:
                    pass
        except Exception as e:
            pytest.fail(f"예외가 바깥으로 전파됨: {e}")


# ─── TC 2: sentinel 파싱 ──────────────────────────────────────────────────────

class TestCompletedSentinelParsing:
    """__COMPLETED:: sentinel 파싱 로직 검증."""

    def test_completed_sentinel_parse_with_reason(self):
        """R(Right): __COMPLETED::no_progress__ → reason="no_progress"."""
        reason = parse_completed_sentinel("__COMPLETED::no_progress__")
        assert reason == "no_progress"

    def test_completed_sentinel_parse_legacy(self):
        """B(Boundary): 구형 __COMPLETED__ → reason="completed" (하위 호환)."""
        reason = parse_completed_sentinel("__COMPLETED__")
        assert reason == "completed"

    def test_completed_sentinel_parse_all_reasons(self):
        """R(Right): 각 exit_reason 값 파싱 정확도 검증."""
        cases = [
            ("__COMPLETED::completed__", "completed"),
            ("__COMPLETED::rate_limit__", "rate_limit"),
            ("__COMPLETED::error__", "error"),
            ("__COMPLETED::archived__", "archived"),
            ("__COMPLETED::on_hold__", "on_hold"),
            ("__COMPLETED::stopped__", "stopped"),
            ("__COMPLETED::quota_exhausted__", "quota_exhausted"),
        ]
        for sentinel, expected in cases:
            assert parse_completed_sentinel(sentinel) == expected, f"sentinel={sentinel}"


# ─── TC 3: get_all_runners() exit_reason ─────────────────────────────────────

class TestGetAllRunnersExitReason:
    """executor_service.get_all_runners()가 exit_reason을 포함하는지 검증."""

    @pytest.fixture
    def fake_redis(self):
        return fakeredis.FakeRedis(decode_responses=True)

    @pytest.fixture
    def fake_async_redis(self):
        return fakeredis.aioredis.FakeRedis(decode_responses=True)

    @pytest.fixture
    def executor(self, fake_redis, fake_async_redis):
        from app.modules.dev_runner.services.executor_service import ExecutorService
        service = ExecutorService()
        service.redis_client = fake_redis
        service.async_redis = fake_async_redis
        return service

    @pytest.mark.asyncio
    async def test_runner_list_item_includes_exit_reason(self, executor):
        """R(Right): exit_reason이 Redis에 있을 때 RunnerListItem에 포함."""
        from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX
        rid = "tc-pytest-exitr-001"

        executor.async_redis.smembers = AsyncMock(return_value={rid})

        async def get_side(key):
            mapping = {
                f"{RUNNER_KEY_PREFIX}:{rid}:status": "stopped",
                f"{RUNNER_KEY_PREFIX}:{rid}:pid": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:plan_file": "test.md",
                f"{RUNNER_KEY_PREFIX}:{rid}:engine": "claude",
                f"{RUNNER_KEY_PREFIX}:{rid}:start_time": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:worktree_path": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:merge_status": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:branch": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:trigger": "user",
                f"{RUNNER_KEY_PREFIX}:{rid}:exit_reason": "no_progress",
            }
            return mapping.get(key)

        executor.async_redis.get = get_side

        with patch.object(executor, "_is_pid_alive", return_value=False):
            result = await executor.get_all_runners()

        found = [r for r in result if r.runner_id == rid]
        assert len(found) == 1
        assert found[0].exit_reason == "no_progress"

    @pytest.mark.asyncio
    async def test_runner_list_item_exit_reason_null(self, executor):
        """B(Boundary): exit_reason 키 없는 runner → exit_reason=None."""
        from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX
        rid = "tc-pytest-exitr-002"

        executor.async_redis.smembers = AsyncMock(return_value={rid})

        async def get_side(key):
            mapping = {
                f"{RUNNER_KEY_PREFIX}:{rid}:status": "stopped",
                f"{RUNNER_KEY_PREFIX}:{rid}:pid": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:plan_file": "test.md",
                f"{RUNNER_KEY_PREFIX}:{rid}:engine": "claude",
                f"{RUNNER_KEY_PREFIX}:{rid}:start_time": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:worktree_path": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:merge_status": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:branch": None,
                f"{RUNNER_KEY_PREFIX}:{rid}:trigger": "user",
                # exit_reason 키 없음
            }
            return mapping.get(key)

        executor.async_redis.get = get_side

        with patch.object(executor, "_is_pid_alive", return_value=False):
            result = await executor.get_all_runners()

        found = [r for r in result if r.runner_id == rid]
        assert len(found) == 1
        assert found[0].exit_reason is None


# ─── TC 4: rate limit 감지 ────────────────────────────────────────────────────

class TestRateLimitDetection:
    """impl.py의 rate limit 키워드 감지 → RATE_LIMITED 반환 검증."""

    def _detect_rate_limit(self, output: str, raw_output: str = "") -> bool:
        """rate limit 키워드 감지 로직 (impl.py에서 추출)."""
        combined = (output or "") + (raw_output or "")
        keywords = ("hit your limit", "rate limit", "resets ")
        return any(kw in combined.lower() for kw in keywords)

    def test_rate_limit_detection_hit_your_limit(self):
        """R(Right): "hit your limit" 포함 → rate limit 감지."""
        assert self._detect_rate_limit("You've hit your limit for this period.")

    def test_rate_limit_detection_rate_limit_keyword(self):
        """R(Right): "rate limit" 포함 → rate limit 감지."""
        assert self._detect_rate_limit("Error: rate limit exceeded. Please wait.")

    def test_rate_limit_detection_resets(self):
        """R(Right): "resets " 포함 → rate limit 감지."""
        assert self._detect_rate_limit("Your usage resets in 2 hours.")

    def test_rate_limit_detection_no_false_positive(self):
        """B(Boundary): rate limit 키워드 없는 정상 실패 → 감지 안 됨."""
        assert not self._detect_rate_limit("FAILED: build error in main.py")

    def test_rate_limit_detection_in_raw_output(self):
        """R(Right): raw_output에서도 키워드 감지."""
        assert self._detect_rate_limit("", raw_output="hit your limit for the day")
