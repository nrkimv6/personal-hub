"""test_invisible_sse_http.py — SSE /events 초기 status에서 visible runner 포함 검증 (T5)

invisible runner가 RECENT set에 있어도 SSE initial status 이벤트에 포함되지 않음을 검증.
visible runner는 포함됨을 검증.

/merge-test 스킬이 main 머지 후 실행.
"""
import json
import time
import pytest
import fakeredis
import fakeredis.aioredis
from unittest.mock import patch, MagicMock

from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.services.event_service import (
    EventService,
    RECENT_RUNNERS_KEY,
    RUNNER_KEY_PREFIX,
    ACTIVE_RUNNERS_KEY,
)

pytestmark = pytest.mark.http


@pytest.fixture
def sync_redis():
    r = fakeredis.FakeRedis(decode_responses=True)
    yield r
    r.close()


@pytest.fixture
def event_service_with_fake_sync(sync_redis):
    """EventService에 fakeredis 주입."""
    svc = EventService.__new__(EventService)
    svc._sync = sync_redis
    return svc


class TestSSEInitialStatusVisibility:

    def test_events_sse_initial_status_includes_visible_http(
        self, event_service_with_fake_sync, sync_redis
    ):
        """T5: visible runner(trigger='user')가 SSE initial status의 runners 배열에 포함됨 검증

        _cleanup_invisible_recent_runners() 호출 후 _build_all_runners_status()가
        visible runner를 반환해야 함.
        """
        svc = event_service_with_fake_sync
        visible_rid = "t5-visible-runner-001"

        # visible runner — RECENT에 등록
        sync_redis.zadd(RECENT_RUNNERS_KEY, {visible_rid: time.time()})
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{visible_rid}:status", "stopped")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{visible_rid}:trigger", "user")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{visible_rid}:plan_file", "docs/plan/test.md")

        # SSE 초기화 시 cleanup 수행 후 status 조회
        svc._cleanup_invisible_recent_runners()
        runners = svc._build_all_runners_status()
        runner_ids = [r["runner_id"] for r in runners]

        assert visible_rid in runner_ids, (
            f"visible runner({visible_rid})가 SSE status에 포함되어야 함\n"
            f"반환된 runner_ids: {runner_ids}"
        )

    def test_events_sse_initial_status_excludes_invisible_http(
        self, event_service_with_fake_sync, sync_redis
    ):
        """T5: invisible runner(trigger=None)만 RECENT에 있으면 runners 배열이 빈 배열

        invisible runner가 RECENT에 있어도 _cleanup_invisible_recent_runners() +
        _build_all_runners_status()의 visible 필터로 완전 제외됨을 검증.
        """
        svc = event_service_with_fake_sync
        invisible_rids = ["t5-invis-001", "t5-invis-002", "t5-invis-003"]

        for rid in invisible_rids:
            sync_redis.zadd(RECENT_RUNNERS_KEY, {rid: time.time()})
            sync_redis.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
            # trigger 미설정 = invisible

        # SSE 초기화 시 cleanup 수행 후 status 조회
        svc._cleanup_invisible_recent_runners()
        runners = svc._build_all_runners_status()

        assert runners == [], (
            f"invisible runner만 있으면 runners 배열이 빈 배열이어야 함\n"
            f"실제 반환: {runners}"
        )
        # RECENT도 비어 있어야 함 (cleanup이 제거했으므로)
        assert sync_redis.zcard(RECENT_RUNNERS_KEY) == 0, (
            "cleanup 후 invisible runner가 RECENT에서 제거되어야 함"
        )
