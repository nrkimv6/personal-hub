"""Redis 연결 누수 HTTP 통합 테스트 — TestClient 기반 SSE + diagnostics 검증.

[MUTATING] restart-frontend tests in this file restart live frontend services.
Run them sequentially; concurrent restart validation can trip the frontend lock.
"""
import time
import sys
import subprocess
from pathlib import Path

import pytest
import redis
import requests

from tests.helpers.restart_frontend_validation import restart_frontend_failure_context


ADMIN_BASE = "http://localhost:8001"
PUBLIC_FRONTEND_BASE = "http://127.0.0.2:6100"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BROWSER_WORKERS_SCRIPT = PROJECT_ROOT / "scripts" / "services" / "browser_workers.py"


def _is_http_env_available() -> bool:
    try:
        requests.get(f"{ADMIN_BASE}/api/v1/system/liveness", timeout=1)
    except Exception:
        return False
    try:
        r = redis.Redis(host="localhost", port=6379, decode_responses=True)
        r.ping()
        r.close()
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _is_http_env_available(),
    reason="admin api 또는 Redis가 실행 중이 아닙니다.",
)


def _run_restart_frontend(*extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BROWSER_WORKERS_SCRIPT), "restart-frontend", *extra_args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        encoding="utf-8",
        errors="replace",
    )


def _wait_until_http_ok(url: str, *, timeout_seconds: float = 20.0, label: str) -> None:
    deadline = time.time() + max(timeout_seconds, 1.0)
    last_error: str | None = None
    while time.time() <= deadline:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                return
            last_error = f"unexpected status: {response.status_code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    pytest.fail(f"{label} did not recover: {url} ({last_error})")


def wait_until_public_preview_ready(timeout_seconds: float = 30.0) -> None:
    _wait_until_http_ok(PUBLIC_FRONTEND_BASE, timeout_seconds=timeout_seconds, label="public preview")


def _assert_no_redis_connection_leak(
    r: redis.Redis,
    before: int,
    *,
    max_delta: int = 1,
    settle_seconds: int = 8,
) -> None:
    """연결 수가 일시적으로 튀는 환경을 고려해 settle 구간의 최소값으로 검증."""
    threshold = before + max_delta
    observed: list[int] = []
    for _ in range(settle_seconds):
        info = r.info("clients")
        observed.append(info.get("connected_clients", 0))
        if observed[-1] <= threshold:
            return
        time.sleep(1)
    raise AssertionError(
        f"연결 누수: before={before}, threshold={threshold}, observed={observed}"
    )


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

    _assert_no_redis_connection_leak(r, before, max_delta=2, settle_seconds=10)
    r.close()


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

    _assert_no_redis_connection_leak(r, before, max_delta=2, settle_seconds=10)
    r.close()


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


def test_redis_cleanup_dry_run_http():
    """redis-cleanup CLI 커맨드 dry-run 검증."""
    import subprocess
    try:
        result = subprocess.run(
            ["D:\\work\\project\\tools\\monitor-page\\.venv\\Scripts\\python.exe",
             "D:\\work\\project\\tools\\monitor-page\\scripts\\services\\browser_workers.py",
             "redis-cleanup"],
            capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        pytest.skip(f"redis-cleanup timeout: {exc.timeout}s")
    assert result.returncode == 0
    # 좀비 연결 없거나 감지 메시지가 있어야 함
    output = result.stdout
    assert "좀비" in output or "Zombie" in output or "redis-cleanup" in output.lower() or "Cleanup" in output


def test_http_frontend_restart_frontend_admin_keeps_api_alive():
    """restart-frontend(admin) 이후 /dev-runner/runners가 200 유지되는지 검증."""
    before = requests.get(f"{ADMIN_BASE}/api/v1/dev-runner/runners", timeout=5)
    assert before.status_code == 200

    result = _run_restart_frontend()
    assert result.returncode == 0, restart_frontend_failure_context(result)
    _wait_until_http_ok(
        f"{ADMIN_BASE}/api/v1/dev-runner/runners",
        timeout_seconds=20.0,
        label="admin runners endpoint",
    )


def test_http_frontend_restart_frontend_public_keeps_api_alive():
    """restart-frontend(--public) 이후 public preview와 admin API가 함께 회복되어야 한다."""
    before = requests.get(f"{ADMIN_BASE}/api/v1/dev-runner/runners", timeout=5)
    assert before.status_code == 200

    result = _run_restart_frontend("--public")
    assert result.returncode == 0, restart_frontend_failure_context(result)
    wait_until_public_preview_ready()
    _wait_until_http_ok(
        f"{ADMIN_BASE}/api/v1/dev-runner/runners",
        timeout_seconds=20.0,
        label="admin runners endpoint after public restart",
    )


def test_http_frontend_restart_frontend_public_invalid_mode_returns_error():
    """잘못된 옵션 조합(status + --public)에서 에러 코드/메시지를 반환해야 한다."""
    result = subprocess.run(
        [sys.executable, str(BROWSER_WORKERS_SCRIPT), "status", "--public"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode != 0
    assert "--public can only be used with restart-frontend" in (result.stderr or "")
