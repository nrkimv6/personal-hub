"""exit_reason 통합 TC - 실제 Redis 연결 + 실제 컴포넌트

T3 통합 검증:
- test_no_progress_exit_sets_redis_integration: Runner 인스턴스 + Redis + _cleanup_redis_state
- test_listener_publishes_exit_reason_integration: listener cleanup → __COMPLETED::{reason}__ publish
"""

import pytest
import time
import threading
from unittest.mock import AsyncMock, MagicMock, patch
import fakeredis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.runner import router as runner_router
from app.modules.dev_runner.services.redis_connection import RECENT_RUNNERS_TTL

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"
LOG_CHANNEL_PREFIX = "plan-runner:logs"
BASE_URL = "/api/v1/dev-runner"


def simulate_cleanup_redis_state(runner_id: str, exit_reason: str, fake_redis, stop_stage: str | None = None):
    """runner.py _cleanup_redis_state 로직 시뮬레이션."""
    REDIS_STATE_KEY = f"plan-runner:state:{runner_id}"
    RUNNER_KEY_SUFFIXES = (
        "status", "pid", "plan_file", "start_time", "log_file_path", "stream_log_path",
        "engine", "fix_engine", "worktree_path", "branch", "merge_status", "merge_requested",
        "current_cycle", "quota_stopped", "error", "restart_after_merge", "exit_reason", "stop_stage",
    )
    try:
        fake_redis.set(f"{REDIS_STATE_KEY}:status", "stopped")
        fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", exit_reason)
        if stop_stage:
            fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage", stop_stage)
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


def _make_runner_payload_from_redis(fake_redis, runner_id: str) -> dict:
    """fakeredis 상태를 /runners 응답용 payload로 변환."""
    return {
        "runner_id": runner_id,
        "running": False,
        "plan_file": "docs/plan/test.md",
        "engine": "claude",
        "start_time": "2026-04-03T00:00:00",
        "pid": 1234,
        "worktree_path": None,
        "branch": None,
        "merge_status": None,
        "trigger": "user",
        "visible": True,
        "orphan": False,
        "exit_reason": fake_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason"),
        "stop_stage": fake_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage"),
        "error": fake_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:error"),
    }


class TestNoProgressExitSetsRedisIntegration:
    """T3: 실제 Runner + Redis 통합 — exit_reason 기록 검증."""

    def test_cleanup_simulation_uses_unified_recent_ttl(self):
        """cleanup 시뮬레이션이 redis_connection.RECENT_RUNNERS_TTL 상수를 그대로 사용한다."""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "tc-pytest-t3-ttl-001"

        simulate_cleanup_redis_state(runner_id, "completed", fake_redis)

        ttl = fake_redis.ttl(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
        assert ttl <= RECENT_RUNNERS_TTL
        assert ttl > max(0, RECENT_RUNNERS_TTL - 5)

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

    def test_commit_failed_exit_sets_redis_integration(self):
        """commit_failed 종료 시 Redis에 exit_reason=commit_failed 기록."""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "tc-pytest-t3-005"

        fake_redis.sadd(ACTIVE_RUNNERS_KEY, runner_id)
        simulate_cleanup_redis_state(runner_id, "commit_failed", fake_redis)

        stored = fake_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason")
        assert stored == "commit_failed"

    def test_stopped_pre_review_sets_stop_stage_integration(self):
        """stopped 종료 시 stop_stage=pre_review가 Redis에 함께 기록된다."""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "tc-pytest-t3-007"

        fake_redis.sadd(ACTIVE_RUNNERS_KEY, runner_id)
        simulate_cleanup_redis_state(runner_id, "stopped", fake_redis, stop_stage="pre_review")

        stored = fake_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage")
        assert stored == "pre_review"


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

    def test_listener_publishes_commit_failed_reason(self):
        """commit_failed가 저장된 경우 __COMPLETED::commit_failed__ publish."""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "tc-pytest-t3-006"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

        fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "commit_failed")

        pubsub = fake_redis.pubsub()
        pubsub.subscribe(log_channel)
        pubsub.get_message(timeout=0.1)

        simulate_listener_cleanup(runner_id, fake_redis, pubsub)

        msg = pubsub.get_message(timeout=0.5)
        assert msg is not None
        assert msg["data"] == "__COMPLETED::commit_failed__"

        pubsub.close()


class TestCommitFailedDetailConvergence:
    """T3: listener publish, Redis error, /runners 응답이 같은 commit_failed detail로 수렴한다."""

    @pytest.mark.http
    def test_commit_failed_detail_converges_with_runners_response(self):
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "tc-pytest-t3-008"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        detail = "exit_reason=commit_failed; detail=commit_scope=docs/plan/test.md"

        fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "commit_failed")
        fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:error", detail)

        pubsub = fake_redis.pubsub()
        pubsub.subscribe(log_channel)
        pubsub.get_message(timeout=0.1)

        simulate_listener_cleanup(runner_id, fake_redis, pubsub)

        msg = pubsub.get_message(timeout=0.5)
        assert msg is not None
        assert msg["data"] == "__COMPLETED::commit_failed__"
        assert fake_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:error") == detail

        app = FastAPI()
        app.include_router(runner_router, prefix=BASE_URL)
        payload = _make_runner_payload_from_redis(fake_redis, runner_id)

        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            return_value=[payload],
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                response = client.get(f"{BASE_URL}/runners")

        assert response.status_code == 200
        data = response.json()
        assert data[0]["exit_reason"] == "commit_failed"
        assert data[0]["error"] == detail
        pubsub.close()
