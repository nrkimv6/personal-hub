"""T5 HTTP: SSE 필터링 HTTP 통합 테스트

Admin API GET /events 엔드포인트의 initial status 응답을 검증한다.

선행 조건:
  - Admin API 서버 실행 중 (localhost:8001)
  - Redis 서버 실행 중 (localhost:6379)

실행: /merge-test에서 main 머지 후 실행할 것
"""

import json
import time

import pytest
import redis as redis_lib
import requests

ADMIN_API = "http://localhost:8001"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
PLAN_FILE_ALL = "__ALL_PLANS__"

SSE_EVENTS_URL = f"{ADMIN_API}/api/v1/dev-runner/events"


def _collect_initial_status_http(timeout: float = 5.0) -> list[dict]:
    """SSE /events 연결 후 초기 status 이벤트의 runners 목록 반환"""
    try:
        with requests.get(SSE_EVENTS_URL, stream=True, timeout=timeout + 1) as resp:
            assert resp.status_code == 200, f"GET /events HTTP {resp.status_code}"
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
                    return json.loads(raw_line[5:].strip()).get("runners", [])
    except Exception:
        pass
    return []


def _is_api_available() -> bool:
    try:
        resp = requests.get(f"{ADMIN_API}/health", timeout=2)
        return resp.status_code < 500
    except Exception:
        return False


@pytest.fixture
def redis_client():
    r = redis_lib.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    yield r
    r.close()


@pytest.mark.skipif(not _is_api_available(), reason="Admin API 서버 미실행")
class TestSseFilterHttp:
    def test_http_events_initial_status_excludes_tc_trigger(self, redis_client):
        """GET /events → initial status → tc:trigger runner 미포함"""
        runner_id = "http_tc_filter_test_01"
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "tc:http-test")
            redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

            runners = _collect_initial_status_http(timeout=5.0)
            runner_ids = [r.get("runner_id") for r in runners]

            assert runner_id not in runner_ids, (
                f"tc: 트리거 runner {runner_id!r}이 HTTP /events initial status에 포함됨"
            )
        finally:
            redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
            for suffix in ("status", "trigger"):
                redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}")

    def test_http_events_plan_file_null_when_key_missing(self, redis_client):
        """GET /events → plan_file 키 없는 running runner → JSON에서 plan_file=null (not __ALL_PLANS__)"""
        runner_id = "http_pf_null_test_01"
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
            # plan_file 키 미설정
            redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

            runners = _collect_initial_status_http(timeout=5.0)
            matching = [r for r in runners if r.get("runner_id") == runner_id]

            assert len(matching) >= 1, f"runner {runner_id!r}이 HTTP /events 결과에 없음"
            plan_file = matching[0].get("plan_file")
            assert plan_file is None, (
                f"plan_file 키 없는 runner에서 plan_file={plan_file!r}. "
                f"null이어야 함 (이전 버그: {PLAN_FILE_ALL!r})"
            )
        finally:
            redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
            for suffix in ("status", "trigger"):
                redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}")

    def test_http_events_plan_file_sentinel_when_explicit(self, redis_client):
        """GET /events → plan_file=__ALL_PLANS__ 명시 → 그대로 __ALL_PLANS__ 반환"""
        runner_id = "http_pf_sentinel_test_01"
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user:all")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", PLAN_FILE_ALL)
            redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

            runners = _collect_initial_status_http(timeout=5.0)
            matching = [r for r in runners if r.get("runner_id") == runner_id]

            assert len(matching) >= 1, f"runner {runner_id!r}이 HTTP /events 결과에 없음"
            assert matching[0].get("plan_file") == PLAN_FILE_ALL
        finally:
            redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
            for suffix in ("status", "trigger", "plan_file"):
                redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}")
