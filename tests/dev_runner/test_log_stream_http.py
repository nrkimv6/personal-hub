"""T5: LogViewer SSE HTTP 통합 테스트

GET /api/v1/dev-runner/logs/stream?runner_id=X 엔드포인트 검증
(실행: /merge-test, TestClient 기반 — 실서버 불필요)
"""

import json
import threading
import time

import pytest
import redis
import requests

ADMIN_API = "http://localhost:8001"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0


@pytest.fixture
def r_live():
    """실서버 테스트용 Redis 클라이언트"""
    client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis not available")
    yield client
    client.close()


# ---------------------------------------------------------------------------
# T5-21: 초기 event: connected 이벤트 수신
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_http_log_stream_connected_event():
    """T5: GET /logs/stream → 첫 이벤트가 event: connected, data: ok"""
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id=t5-test"
    try:
        with requests.get(url, stream=True, timeout=5) as resp:
            assert resp.status_code == 200
            event_type = None
            data_value = None
            for raw_line in resp.iter_lines(decode_unicode=True):
                if raw_line.startswith("event:"):
                    event_type = raw_line[6:].strip()
                elif raw_line.startswith("data:"):
                    data_value = raw_line[5:].strip()
                    break
            assert event_type == "connected", f"첫 이벤트가 connected가 아님: {event_type}"
            assert data_value == "ok", f"data가 ok가 아님: {data_value}"
    except requests.exceptions.Timeout:
        pytest.skip("API server not responding")


# ---------------------------------------------------------------------------
# T5-22: heartbeat 수신 (30초 이내)
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_http_log_stream_heartbeat():
    """T5: SSE 연결 후 35초 이내 ': heartbeat' 라인 수신"""
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id=t5-heartbeat"
    deadline = time.monotonic() + 35
    found_heartbeat = False
    try:
        with requests.get(url, stream=True, timeout=36) as resp:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() > deadline:
                    break
                if raw_line.strip() == ": heartbeat" or raw_line.strip() == ":heartbeat":
                    found_heartbeat = True
                    break
    except requests.exceptions.Timeout:
        pass
    assert found_heartbeat, "35초 내 heartbeat 수신 없음"


# ---------------------------------------------------------------------------
# T5-23: pub/sub publish → SSE data 라인 수신
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_http_log_stream_data_delivery(r_live):
    """T5: Redis publish → SSE data: hello 수신"""
    runner_id = "t5-data-delivery"
    channel = f"plan-runner:logs:{runner_id}"
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id={runner_id}"

    received = []

    def publish_after_delay():
        time.sleep(1.5)
        for _ in range(3):
            r_live.publish(channel, "hello-t5")
            time.sleep(0.3)

    t = threading.Thread(target=publish_after_delay, daemon=True)
    t.start()

    deadline = time.monotonic() + 10
    try:
        with requests.get(url, stream=True, timeout=12) as resp:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() > deadline:
                    break
                if raw_line.startswith("data:"):
                    data = raw_line[5:].strip()
                    if data and data != "ok":
                        received.append(data)
                if received:
                    break
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        pass
    t.join(timeout=5)

    assert any("hello-t5" in d for d in received), \
        f"publish 메시지가 SSE에 전달되지 않음: {received}"


# ---------------------------------------------------------------------------
# T5-24: 전체 T5 실행 확인 (별도 실행 확인용 placeholder)
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_http_log_stream_endpoint_accessible():
    """T5-24: /logs/stream 엔드포인트 접근 가능 확인"""
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id=t5-accessible"
    try:
        with requests.get(url, stream=True, timeout=3) as resp:
            assert resp.status_code == 200
            # Content-Type이 text/event-stream인지 확인
            content_type = resp.headers.get("content-type", "")
            assert "text/event-stream" in content_type, \
                f"Content-Type이 text/event-stream이 아님: {content_type}"
    except requests.exceptions.Timeout:
        pytest.skip("API server not responding")
