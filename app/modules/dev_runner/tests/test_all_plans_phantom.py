"""Phase T3: "전체 실행" 유령 러너 재현 TC

이전 버그 재현 및 수정 후 동작 검증:
  1. tc: 트리거 runner가 SSE에서 필터링되는지 확인
  2. plan_file 키 없을 때 None 반환 (이전: PLAN_FILE_ALL sentinel)
"""

import pytest
import fakeredis

from app.modules.dev_runner.services.event_service import (
    EventService, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, PLAN_FILE_ALL,
)


@pytest.fixture
def sync_redis():
    r = fakeredis.FakeRedis(decode_responses=True)
    yield r
    r.close()


@pytest.fixture
def async_redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r


@pytest.fixture
def event_service(sync_redis, async_redis):
    import fakeredis.aioredis
    svc = EventService.__new__(EventService)
    svc._sync = sync_redis
    svc._async = async_redis
    return svc


class TestPhantomAllPlansRegression:
    def test_tc_trigger_runner_excluded_from_sse(self, event_service, sync_redis):
        """이전 버그: trigger="tc:test" runner가 SSE에 포함되어 "전체 실행" 탭 생성
        수정 후: _build_all_runners_status()에서 tc: 트리거 runner 필터링
        """
        runner_id = "phantom_tc_01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "tc:pytest-auto")
        # plan_file 없음 → 이전에는 PLAN_FILE_ALL sentinel → 프론트에서 "전체 실행" 탭 생성
        sync_redis.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        result = event_service._build_all_runners_status()
        ids = [r["runner_id"] for r in result]

        assert runner_id not in ids, (
            f"tc: 트리거 runner {runner_id!r}이 SSE에 포함됨 (버그 재현). "
            f"필터링이 동작하지 않음."
        )

    def test_phantom_all_plans_when_plan_file_key_missing(self, event_service, sync_redis):
        """이전 버그: plan_file 키 없는 running runner → PLAN_FILE_ALL sentinel 반환
        → 프론트에서 "전체 실행" 탭으로 표시
        수정 후: plan_file is None 반환 → 프론트에서 "(알 수 없음)" 표시
        """
        runner_id = "phantom_nopf_01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        # plan_file 키 의도적으로 미설정

        payload = event_service._build_status_payload(runner_id)

        assert payload is not None
        assert payload["plan_file"] is None, (
            f"plan_file 키 없는 running runner에서 {payload['plan_file']!r}가 반환됨. "
            f"None이어야 함 (이전 버그: PLAN_FILE_ALL = {PLAN_FILE_ALL!r})"
        )

    def test_explicit_all_plans_sentinel_still_works(self, event_service, sync_redis):
        """정상 케이스: plan_file=PLAN_FILE_ALL + user trigger 명시 → sentinel 그대로 반환"""
        runner_id = "phantom_explicit_01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", PLAN_FILE_ALL)
        sync_redis.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        result = event_service._build_all_runners_status()
        matching = [r for r in result if r["runner_id"] == runner_id]

        assert len(matching) == 1, "명시적 sentinel runner가 결과에 미포함"
        assert matching[0]["plan_file"] == PLAN_FILE_ALL
