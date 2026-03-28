"""Redis 연결 누수 HTTP 통합 테스트 — TestClient 기반 SSE + diagnostics 검증."""
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
def test_sse_events_connection_cleanup_http():
    """GET /api/v1/dev-runner/events SSE 연결 → 초기 이벤트 수신 → close → 연결 수 검증."""
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)

    info_before = r.info("clients")
    before = info_before.get("connected_clients", 0)

    session = requests.Session()
    try:
        resp = session.get(
            f"{ADMIN_BASE}/api/v1/dev-runner/events",
            stream=True, timeout=5,
            headers={"Accept": "text/event-stream"},
        )
        events = []
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                events.append(line)
            if len(events) >= 3:  # connected + status 정도
                break
        # connected와 status 이벤트 확인
        text = "\n".join(events)
        assert "connected" in text or "status" in text
    except requests.exceptions.ReadTimeout:
        pass
    finally:
        session.close()

    time.sleep(5)

    info_after = r.info("clients")
    after = info_after.get("connected_clients", 0)

    assert after <= before + 1, f"연결 누수: before={before}, after={after}"
    r.close()


@pytest.mark.skipif(not _server_available(), reason="Admin API not available")
@pytest.mark.skipif(not _redis_available(), reason="Redis not available")
def test_sse_log_stream_nonexistent_runner_http():
    """GET /api/v1/dev-runner/logs/stream?runner_id=nonexistent → close → 누수 없음."""
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)

    info_before = r.info("clients")
    before = info_before.get("connected_clients", 0)

    session = requests.Session()
    try:
        resp = session.get(
            f"{ADMIN_BASE}/api/v1/dev-runner/logs/stream?runner_id=nonexistent",
            stream=True, timeout=5,
            headers={"Accept": "text/event-stream"},
        )
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                break
    except requests.exceptions.ReadTimeout:
        pass
    finally:
        session.close()

    time.sleep(3)

    info_after = r.info("clients")
    after = info_after.get("connected_clients", 0)

    assert after <= before + 1, f"연결 누수: before={before}, after={after}"
    r.close()


@pytest.mark.skipif(not _server_available(), reason="Admin API not available")
def test_diagnostics_redis_connection_count_http():
    """GET /api/v1/dev-runner/logs/diagnostics → 'Redis 연결 수' step 포함 확인."""
    resp = requests.get(f"{ADMIN_BASE}/api/v1/dev-runner/logs/diagnostics", timeout=10)
    assert resp.status_code == 200

    data = resp.json()
    steps = data.get("steps", [])
    conn_step = next((s for s in steps if "연결 수" in s.get("name", "")), None)
    assert conn_step is not None, f"'Redis 연결 수' step 없음: {[s['name'] for s in steps]}"
    assert "detail" in conn_step
    # detail에 숫자가 포함되어야 함
    assert any(c.isdigit() for c in conn_step["detail"]), f"연결 수 값 없음: {conn_step['detail']}"


@pytest.mark.skipif(not _server_available(), reason="Admin API not available")
def test_redis_cleanup_dry_run_http():
    """redis-cleanup CLI 커맨드 dry-run 검증."""
    import subprocess
    result = subprocess.run(
        ["D:\\work\\project\\tools\\monitor-page\\.venv\\Scripts\\python.exe",
         "D:\\work\\project\\tools\\monitor-page\\scripts\\browser_workers.py",
         "redis-cleanup"],
        capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0
    # 좀비 연결 없거나 감지 메시지가 있어야 함
    output = result.stdout
    assert "좀비" in output or "Zombie" in output or "redis-cleanup" in output.lower() or "Cleanup" in output
