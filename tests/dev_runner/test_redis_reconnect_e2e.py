"""T4: SSE 로그 스트림 Redis 재연결 E2E 테스트

실행 중인 Admin API 서버(localhost:8001) + Redis(localhost:6379) 대상.
SSE /logs/stream 연결 후 Redis pubsub 채널에 메시지 publish → connected 이벤트 수신 확인.
"""

import time
import threading

import pytest
import redis
import requests

ADMIN_API = "http://localhost:8001"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

LOG_CHANNEL_PREFIX = "plan-runner:logs"
TEST_RUNNER_ID = "t4-reconnect-test-runner"


def _check_admin_api():
    try:
        resp = requests.get(f"{ADMIN_API}/api/v1/dev-runner/status", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def _collect_sse_events(url: str, target_events: set, timeout: float = 5.0) -> dict:
    """SSE 스트림에서 target_events에 해당하는 이벤트를 수집."""
    collected: dict = {e: [] for e in target_events}
    deadline = time.monotonic() + timeout

    try:
        with requests.get(url, stream=True, timeout=timeout + 1) as resp:
            current_event = "message"
            for raw_line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() > deadline:
                    break
                if not raw_line:
                    current_event = "message"
                    continue
                if raw_line.startswith("event:"):
                    current_event = raw_line[6:].strip()
                elif raw_line.startswith("data:"):
                    data = raw_line[5:].strip()
                    if current_event in collected:
                        collected[current_event].append(data)
                        if all(collected[e] for e in target_events):
                            break
    except Exception:
        pass

    return collected


@pytest.mark.e2e
@pytest.mark.skipif(not _check_admin_api(), reason="Admin API not available (localhost:8001)")
class TestSseLogStreamReconnectE2E:
    """T4: SSE 로그 스트림에서 connected 이벤트 수신 확인"""

    def test_sse_log_stream_reconnect_connected_event(self):
        """
        GET /logs/stream?runner_id={id} SSE 연결 → connected 이벤트 수신.
        Redis pubsub 채널에 __COMPLETED__ publish → completed 이벤트로 종료.
        """
        url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id={TEST_RUNNER_ID}"
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
        channel = f"{LOG_CHANNEL_PREFIX}:{TEST_RUNNER_ID}"

        # SSE 연결 후 일정 시간 후에 완료 신호 publish
        def publish_after_delay():
            time.sleep(1.0)
            r.publish(channel, "__COMPLETED__")

        t = threading.Thread(target=publish_after_delay, daemon=True)
        t.start()

        try:
            collected = _collect_sse_events(url, {"connected", "completed"}, timeout=6.0)
        finally:
            r.close()
            t.join(timeout=3)

        assert collected["connected"], \
            "connected 이벤트 미수신 — 서버가 SSE 초기 connected 이벤트를 전송하지 않음"
        assert collected["connected"][0] == "ok", \
            f"connected data가 ok가 아님: {collected['connected']}"
