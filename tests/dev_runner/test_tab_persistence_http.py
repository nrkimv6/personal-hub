"""T5 HTTP 통합 테스트: 탭 영속화 — 503 응답 + SSE RECENT visible

Phase T5:
- test_runners_endpoint_503_http: GET /runners → Redis ConnectionError → 503 (TestClient)
- test_sse_events_recent_runner_visible_http_live: GET /events → RECENT runner SSE 포함 (실서버)

선행 조건 (http_live):
  - Admin API 서버 실행 중 (localhost:8001)
  - Redis 서버 실행 중 (localhost:6379)
"""

import json
import time
import uuid
from unittest.mock import patch

import pytest
import redis as redis_lib
import requests

ADMIN_API = "http://localhost:8001"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"


def _collect_initial_status_http(timeout: float = 5.0) -> list[dict]:
    """SSE /events 연결 후 초기 status 이벤트의 runners 목록 반환"""
    try:
        url = f"{ADMIN_API}/api/v1/dev-runner/events"
        with requests.get(url, stream=True, timeout=timeout + 1) as resp:
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


@pytest.mark.http
class TestRunnersEndpoint503Http:
    """T5 (http): GET /runners → Redis 연결 에러 시 503 응답"""

    def test_runners_endpoint_503_http(self):
        """T5: async_redis ConnectionError → GET /runners → 503 (TestClient)"""
        import redis
        from fastapi.testclient import TestClient
        from app.main import app
        from app.modules.dev_runner.services.executor_service import executor_service

        client = TestClient(app, raise_server_exceptions=False)

        with patch.object(
            executor_service.async_redis,
            "smembers",
            side_effect=redis.ConnectionError("t5-http-test"),
        ):
            response = client.get("/api/v1/dev-runner/runners")

        assert response.status_code == 503, (
            f"Redis ConnectionError 시 503이 아닌 {response.status_code} 반환됨\n"
            f"응답: {response.text}"
        )

@pytest.mark.http_live
@pytest.mark.allow_prod_redis
class TestSseRecentVisibleHttpLive:
    """T5 (http_live): SSE initial status 이벤트에 RECENT visible 러너 포함 검증"""

    def test_sse_events_recent_runner_visible_http_live(self):
        """T5: RECENT_RUNNERS_KEY에 trigger='user' 러너 등록 → SSE initial status에 포함 확인"""
        r = redis_lib.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        runner_id = f"user-t5-{uuid.uuid4().hex[:8]}"
        score = time.time()

        try:
            # RECENT에 등록 (ACTIVE 아님 — RECENT SSE 포함 검증이 목적)
            r.zadd(RECENT_RUNNERS_KEY, {runner_id: score})
            r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
            r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
            r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")

            # SSE initial status 수집 (최대 10초 재시도)
            deadline = time.monotonic() + 10.0
            found = False
            while time.monotonic() < deadline and not found:
                runners = _collect_initial_status_http(timeout=5.0)
                if any(r_item.get("runner_id") == runner_id for r_item in runners):
                    found = True
                else:
                    time.sleep(0.5)

            runner_ids = [r_item.get("runner_id") for r_item in _collect_initial_status_http()]
            assert found, (
                f"RECENT의 trigger='user' 러너({runner_id})가 SSE initial status에 없음\n"
                f"  수신된 runner_ids: {runner_ids}\n"
                f"  이 실패는 _build_all_runners_status()의 RECENT 포함 로직 회귀를 의미합니다."
            )
        finally:
            r.zrem(RECENT_RUNNERS_KEY, runner_id)
            for suffix in ("status", "trigger", "plan_file"):
                r.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}")
            r.close()
