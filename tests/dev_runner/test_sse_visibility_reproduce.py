"""7차 재발 재현 TC — SSE _build_all_runners_status() 화이트리스트 검증

7차 재발의 핵심 원인: event_service.py의 _build_all_runners_status()가
블랙리스트(tc: 접두사만 제외)를 사용하여 trigger=None/api/manual 등
화이트리스트에 없는 runner가 SSE를 통해 UI에 노출됨.

이 TC들은 수정 후 방어 확인 + 향후 재발 조기 감지용 재현 테스트다.
"""

import pytest
import fakeredis
import fakeredis.aioredis

from app.modules.dev_runner.services.event_service import (
    EventService, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def sync_redis():
    r = fakeredis.FakeRedis(decode_responses=True)
    yield r
    r.close()


@pytest.fixture
def event_service(sync_redis):
    svc = EventService.__new__(EventService)
    svc._sync = sync_redis
    svc._async = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return svc


def _register_runner(r, runner_id: str, trigger=None):
    """Redis에 runner 등록 (trigger 키 없으면 생략)"""
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "some/plan.md")
    if trigger is not None:
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", trigger)
    r.sadd(ACTIVE_RUNNERS_KEY, runner_id)


# ─── 7차 재발 재현 TC ────────────────────────────────────────────────────────

class TestReproduceSeventhRecurrence:

    def test_reproduce_7th_recurrence_trigger_none(self, event_service, sync_redis):
        """7차 핵심 재현: Redis에 trigger 키 없는 runner → SSE에 미포함

        7차 재발 원인: trigger=None runner가 블랙리스트(tc: 아님)로 포함됨.
        화이트리스트 전환 후: trigger=None → is_visible_runner() → False → 미포함.
        """
        _register_runner(sync_redis, "pytest-no-trigger-runner", trigger=None)
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "pytest-no-trigger-runner" not in ids, (
            "trigger=None runner가 SSE에 포함됨 — 7차 재발 재현. "
            "event_service.py의 _build_all_runners_status()가 화이트리스트를 사용하는지 확인."
        )

    def test_reproduce_7th_recurrence_trigger_api(self, event_service, sync_redis):
        """guard 우회 mock 시나리오: trigger='api' runner → SSE에 미포함

        guard fixture가 start_dev_runner를 mock하는 테스트에서
        mock이 trigger='api'로 runner를 생성하면 guard를 우회하여 노출될 수 있다.
        화이트리스트 전환 후: trigger='api' → is_visible_runner() → False → 미포함.
        """
        _register_runner(sync_redis, "api-trigger-runner", trigger="api")
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "api-trigger-runner" not in ids, (
            "trigger='api' runner가 SSE에 포함됨 — guard 우회 시나리오. "
            "is_visible_runner()가 'api' trigger를 거부하는지 확인."
        )

    def test_reproduce_7th_recurrence_trigger_user(self, event_service, sync_redis):
        """정상 시나리오: trigger='user' runner → SSE에 포함

        화이트리스트 전환 후 정상 사용자 runner는 계속 표시되어야 한다.
        """
        _register_runner(sync_redis, "user-trigger-runner", trigger="user")
        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]
        assert "user-trigger-runner" in ids, (
            "trigger='user' runner가 SSE에 미포함됨 — 정상 runner가 필터링됨. "
            "is_visible_runner()의 화이트리스트 확인."
        )
