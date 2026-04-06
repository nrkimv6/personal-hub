"""Redis 연결 누수 E2E 테스트 — 실서버 SSE 연결 후 disconnect 시 cleanup 확인."""
import time

import pytest
import redis
import requests


ADMIN_BASE = "http://localhost:8001"


def _server_available() -> bool:
    try:
        r = requests.get(f"{ADMIN_BASE}/api/v1/dev-runner/runners", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _redis_available() -> bool:
    try:
        r = redis.Redis(host="localhost", port=6379, socket_connect_timeout=2)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _server_available(), reason="Admin API not available")
@pytest.mark.skipif(not _redis_available(), reason="Redis not available")
def test_sse_events_disconnect_cleanup_e2e():
    """Admin API /events SSE 연결 후 session close → Redis 연결 수 감소 확인."""
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)

    info_before = r.info("clients")
    before = info_before.get("connected_clients", 0)

    # SSE 연결
    session = requests.Session()
    try:
        resp = session.get(
            f"{ADMIN_BASE}/api/v1/dev-runner/events",
            stream=True,
            timeout=5,
            headers={"Accept": "text/event-stream"},
        )
        # 첫 이벤트 읽기
        for line in resp.iter_lines(decode_unicode=True):
            if line and "connected" in line:
                break
    except requests.exceptions.ReadTimeout:
        pass
    except requests.exceptions.ConnectionError:
        pytest.skip("Admin API unavailable during test run")
    finally:
        session.close()

    # cleanup 대기
    time.sleep(3)

    info_after = r.info("clients")
    after = info_after.get("connected_clients", 0)

    # SSE 연결 해제 후 연결 수가 크게 증가하지 않음
    assert after <= before + 2, f"연결 누수 의심: before={before}, after={after}"
    r.close()


@pytest.mark.skipif(not _server_available(), reason="Admin API not available")
@pytest.mark.skipif(not _redis_available(), reason="Redis not available")
def test_sse_log_stream_disconnect_cleanup_e2e():
    """SSE /logs/stream 연결 후 close → 연결 누수 없음 확인."""
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)

    info_before = r.info("clients")
    before = info_before.get("connected_clients", 0)

    session = requests.Session()
    try:
        resp = session.get(
            f"{ADMIN_BASE}/api/v1/dev-runner/logs/stream?runner_id=nonexistent-test",
            stream=True,
            timeout=5,
            headers={"Accept": "text/event-stream"},
        )
        for line in resp.iter_lines(decode_unicode=True):
            if line and ("connected" in line or "error" in line):
                break
    except requests.exceptions.ReadTimeout:
        pass
    except requests.exceptions.ConnectionError:
        pytest.skip("Admin API unavailable during test run")
    finally:
        session.close()

    time.sleep(3)

    info_after = r.info("clients")
    after = info_after.get("connected_clients", 0)

    assert after <= before + 2, f"연결 누수 의심: before={before}, after={after}"
    r.close()
