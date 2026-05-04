"""Redis 연결 누수 E2E 테스트 — 실서버 SSE 연결 후 disconnect 시 cleanup 확인."""
import time

import pytest
import redis
import requests

pytestmark = pytest.mark.http_live


ADMIN_BASE = "http://localhost:8001"


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
        pytest.fail("Admin API unavailable during test run")
    finally:
        session.close()

    # cleanup 반영 대기 (단일 스냅샷 대신 폴링 최소값 사용)
    after_samples = []
    for _ in range(6):
        time.sleep(0.5)
        info_after = r.info("clients")
        after_samples.append(info_after.get("connected_clients", 0))
    after = min(after_samples) if after_samples else before

    # SSE 연결 해제 후 연결 수가 크게 증가하지 않음
    assert after <= before + 2, f"연결 누수 의심: before={before}, after={after}"
    r.close()


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
        pytest.fail("Admin API unavailable during test run")
    finally:
        session.close()

    after_samples = []
    for _ in range(6):
        time.sleep(0.5)
        info_after = r.info("clients")
        after_samples.append(info_after.get("connected_clients", 0))
    after = min(after_samples) if after_samples else before

    assert after <= before + 2, f"연결 누수 의심: before={before}, after={after}"
    r.close()
