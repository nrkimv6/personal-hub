"""T4 E2E: SSE 필터링 통합 테스트

실행 중인 Admin API 서버(localhost:8001) + Redis를 대상으로
tc: 트리거 runner 필터링을 검증한다.

선행 조건:
  - Admin API 서버 실행 중 (localhost:8001)
  - Redis 서버 실행 중 (localhost:6379)

실행: /merge-test에서 main 머지 후 실행할 것

⚠️ trigger="user"/"user:all"을 프로덕션 Redis에 직접 SET 금지 — 유령 탭 오염 원인.
   visible runner 검증은 app/modules/dev_runner/tests/test_event_service.py에서 fakeredis로 수행.
"""

import json
import time
import uuid

import pytest
import redis as redis_lib
import requests

ADMIN_API = "http://localhost:8001"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"

SSE_EVENTS_URL = f"{ADMIN_API}/api/v1/dev-runner/events"


def _collect_initial_status(timeout: float = 5.0) -> list[dict]:
    """SSE /events 연결 후 초기 status 이벤트의 runners 목록 반환"""
    try:
        with requests.get(SSE_EVENTS_URL, stream=True, timeout=timeout + 1) as resp:
            current_event = "message"
            deadline = time.monotonic() + timeout
            for raw_line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() > deadline:
                    break
                if not raw_line:
                    current_event = "message"
                    continue
                if raw_line.startswith("event:"):
                    current_event = raw_line[6:].strip()
                elif raw_line.startswith("data:") and current_event == "status":
                    data = json.loads(raw_line[5:].strip())
                    return data.get("runners", [])
    except Exception:
        pass
    return []


@pytest.fixture
def redis_client():
    r = redis_lib.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    yield r
    r.close()


def _is_api_available() -> bool:
    try:
        resp = requests.get(f"{ADMIN_API}/health", timeout=2)
        return resp.status_code < 500
    except Exception:
        return False


@pytest.mark.skipif(not _is_api_available(), reason="Admin API 서버 미실행")
@pytest.mark.allow_prod_redis
class TestSseFilterE2E:
    def test_sse_initial_status_excludes_tc_trigger_runner(self, redis_client):
        """Redis에 trigger="tc:test" runner 등록 → SSE /events initial status에 미포함"""
        runner_id = f"tc-pytest-{uuid.uuid4().hex[:8]}"
        try:
            # runner 등록
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "tc:pytest-e2e")
            redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

            runners = _collect_initial_status(timeout=5.0)
            runner_ids = [r.get("runner_id") for r in runners]

            assert runner_id not in runner_ids, (
                f"tc: 트리거 runner {runner_id!r}이 SSE initial status에 포함됨. "
                f"필터링이 동작하지 않음. runners: {runner_ids}"
            )
        finally:
            redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
            for suffix in ("status", "trigger"):
                redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}")
            # cleanup 확인: 키 잔류 0건 보장
            remaining = redis_client.keys(f"{RUNNER_KEY_PREFIX}:{runner_id}:*")
            assert remaining == [], f"cleanup 후 키 잔류: {remaining}"
            assert not redis_client.sismember(ACTIVE_RUNNERS_KEY, runner_id), (
                f"cleanup 후 {runner_id!r}이 {ACTIVE_RUNNERS_KEY}에 잔류"
            )

    def test_sse_status_event_after_tc_runner_start(self, redis_client):
        """tc:test runner를 active_runners에 추가해도 SSE status 이벤트에 tc: runner 미포함"""
        runner_id = f"tc-pytest-{uuid.uuid4().hex[:8]}"
        try:
            # tc: runner 등록
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "tc:auto")
            redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

            # SSE 초기 status에서 확인
            runners = _collect_initial_status(timeout=5.0)
            runner_ids = [r.get("runner_id") for r in runners]

            assert runner_id not in runner_ids, (
                f"tc: 트리거 runner {runner_id!r}이 포함됨"
            )
        finally:
            redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
            for suffix in ("status", "trigger"):
                redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}")
            # cleanup 확인: 키 잔류 0건 보장
            remaining = redis_client.keys(f"{RUNNER_KEY_PREFIX}:{runner_id}:*")
            assert remaining == [], f"cleanup 후 키 잔류: {remaining}"
            assert not redis_client.sismember(ACTIVE_RUNNERS_KEY, runner_id), (
                f"cleanup 후 {runner_id!r}이 {ACTIVE_RUNNERS_KEY}에 잔류"
            )

