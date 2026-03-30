"""T4: LogViewer SSE 스트리밍 E2E 테스트

Redis pub/sub → SSE /logs/stream 전체 경로 검증
(실행: /merge-test, 실서버 localhost:8001 + Redis 필요)
"""

import threading
import time

import pytest
import redis
import requests

ADMIN_API = "http://localhost:8001"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
LOG_CHANNEL_PREFIX = "plan-runner:logs"


def _collect_sse_data_lines(url: str, timeout: float = 8.0) -> list[str]:
    """SSE 스트림에서 data: 라인을 수집"""
    collected = []
    deadline = time.monotonic() + timeout
    try:
        with requests.get(url, stream=True, timeout=timeout + 2) as resp:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() > deadline:
                    break
                if raw_line and raw_line.startswith("data:"):
                    data = raw_line[5:].strip()
                    if data and data != "ok":
                        collected.append(data)
                if len(collected) >= 3:
                    break
    except Exception:
        pass
    return collected


@pytest.fixture
def r():
    client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis not available")
    yield client
    client.close()


# ---------------------------------------------------------------------------
# T4-19: Redis pub/sub → SSE data 라인 수신 (E2E)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_e2e_log_stream_receives_published_lines(r):
    """E2E: Redis publish → SSE /logs/stream data 라인 수신 확인"""
    runner_id = "t4-log-stream-test"
    channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id={runner_id}"

    published_lines = []

    def publish_after_delay():
        time.sleep(1.5)  # SSE 연결 대기
        for i in range(3):
            line = f"test-line-{i}"
            r.publish(channel, line)
            published_lines.append(line)
            time.sleep(0.3)

    t = threading.Thread(target=publish_after_delay, daemon=True)
    t.start()

    collected = _collect_sse_data_lines(url, timeout=8.0)
    t.join(timeout=5)

    assert len(collected) >= 1, f"SSE data: 라인이 수신되지 않음. published={published_lines}"
    assert any("test-line" in c for c in collected), f"published 라인이 SSE에 없음: {collected}"


# ---------------------------------------------------------------------------
# T4-20: pub/sub 미수신 시 파일 폴링 fallback E2E
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_e2e_log_stream_fallback_on_no_pubsub(r, tmp_path):
    """E2E: pub/sub publish 없이 파일 폴링 fallback으로 내용 수신 (5초 대기)"""
    import os

    runner_id = "t4-fallback-test"
    log_key = f"plan-runner:stream_log_path:{runner_id}"
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id={runner_id}"

    # 임시 로그 파일 생성
    log_file = tmp_path / "fallback_test.log"
    log_file.write_text("fallback-line-1\n" * 15 + "fallback-line-2\n" * 5, encoding="utf-8")

    # Redis에 stream_log_path 설정 (plan-runner:runners:{runner_id}:stream_log_path)
    correct_key = f"plan-runner:runners:{runner_id}:stream_log_path"
    r.set(correct_key, str(log_file))
    try:
        # pub/sub publish 없이 SSE 연결 — 5초 후 파일 폴링 전환
        collected = _collect_sse_data_lines(url, timeout=10.0)

        # 파일 내용이 SSE로 전달되어야 함
        assert any("fallback-line" in c for c in collected), \
            f"파일 폴링 fallback 미작동: collected={collected}"
    finally:
        r.delete(f"plan-runner:runners:{runner_id}:stream_log_path")
