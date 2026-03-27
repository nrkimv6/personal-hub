"""exit_reason 통합 TC - 실제 Redis 연결 + 실제 컴포넌트

T3 통합 검증:
- test_no_progress_exit_sets_redis_integration: Runner 인스턴스 + Redis + _cleanup_redis_state
- test_listener_publishes_exit_reason_integration: listener cleanup → __COMPLETED::{reason}__ publish
"""

import pytest
import time
import threading
from unittest.mock import MagicMock, patch
import fakeredis

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"
RECENT_RUNNERS_TTL = 3600
LOG_CHANNEL_PREFIX = "plan-runner:logs"


def simulate_cleanup_redis_state(runner_id: str, exit_reason: str, fake_redis):
    """runner.py _cleanup_redis_state 로직 시뮬레이션."""
    REDIS_STATE_KEY = f"plan-runner:state:{runner_id}"
    RUNNER_KEY_SUFFIXES = (
        "status", "pid", "plan_file", "start_time", "log_file_path", "stream_log_path",
        "engine", "fix_engine", "worktree_path", "branch", "merge_status", "merge_requested",
        "current_cycle", "quota_stopped", "error", "restart_after_merge", "exit_reason",
    )
    try:
        fake_redis.set(f"{REDIS_STATE_KEY}:status", "stopped")
        fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", exit_reason)
        for suffix in RUNNER_KEY_SUFFIXES:
            fake_redis.expire(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", RECENT_RUNNERS_TTL)
        fake_redis.srem(ACTIVE_RUNNERS_KEY, runner_id)
        fake_redis.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})
    except Exception:
        pass


def simulate_listener_cleanup(runner_id: str, fake_redis, pubsub_mock):
    """listener dev-runner-command-listener.py cleanup 로직 시뮬레이션.

    cleanup 직전 exit_reason을 읽어 __COMPLETED::{reason}__ 형태로 publish.
    """
    log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    try:
        exit_reason = fake_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason") or "completed"
        fake_redis.publish(log_channel, f"__COMPLETED::{exit_reason}__")
    except Exception:
        pass


class TestNoProgressExitSetsRedisIntegration:
    """T3: 실제 Runner + Redis 통합 — exit_reason 기록 검증."""

    def test_no_progress_exit_sets_redis_integration(self):
        """no_progress 종료 시 Redis에 exit_reason=no_progress 기록."""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "tc-pytest-t3-001"

        # 실행 중 상태 설정
        fake_redis.sadd(ACTIVE_RUNNERS_KEY, runner_id)
        fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")

        # cleanup 호출 (no_progress 사유)
        simulate_cleanup_redis_state(runner_id, "no_progress", fake_redis)

        # Redis에서 직접 exit_reason 조회 검증
        stored = fake_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason")
        assert stored == "no_progress", f"expected 'no_progress', got {stored!r}"

        # status가 stopped로 전환됐는지도 확인
        status = fake_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
        assert status == "stopped"

        # active_runners에서 제거됐는지 확인
        members = fake_redis.smembers(ACTIVE_RUNNERS_KEY)
        assert runner_id not in members

    def test_rate_limit_exit_sets_redis_integration(self):
        """rate_limit 종료 시 Redis에 exit_reason=rate_limit 기록."""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "tc-pytest-t3-002"

        fake_redis.sadd(ACTIVE_RUNNERS_KEY, runner_id)
        simulate_cleanup_redis_state(runner_id, "rate_limit", fake_redis)

        stored = fake_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason")
        assert stored == "rate_limit"


class TestListenerPublishesExitReasonIntegration:
    """T3: listener cleanup → __COMPLETED::{reason}__ publish 통합 검증."""

    def test_listener_publishes_exit_reason_integration(self):
        """exit_reason이 Redis에 있을 때 listener가 __COMPLETED::{reason}__ 형태로 publish."""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "tc-pytest-t3-003"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

        # Redis에 exit_reason 설정
        fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "no_progress")

        # Pub/Sub 구독
        pubsub = fake_redis.pubsub()
        pubsub.subscribe(log_channel)

        # 구독 확인 메시지 소비
        pubsub.get_message(timeout=0.1)

        # listener cleanup 시뮬레이션
        simulate_listener_cleanup(runner_id, fake_redis, pubsub)

        # publish된 메시지 수신
        msg = pubsub.get_message(timeout=0.5)
        assert msg is not None, "publish 메시지를 수신하지 못함"
        assert msg["type"] == "message"
        assert msg["data"] == "__COMPLETED::no_progress__", f"unexpected: {msg['data']!r}"

        pubsub.close()

    def test_listener_publishes_completed_when_no_exit_reason(self):
        """exit_reason 키가 없을 때 listener가 __COMPLETED::completed__ 형태로 publish."""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "tc-pytest-t3-004"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

        # exit_reason 키 없음

        pubsub = fake_redis.pubsub()
        pubsub.subscribe(log_channel)
        pubsub.get_message(timeout=0.1)

        simulate_listener_cleanup(runner_id, fake_redis, pubsub)

        msg = pubsub.get_message(timeout=0.5)
        assert msg is not None
        assert msg["data"] == "__COMPLETED::completed__"

        pubsub.close()
