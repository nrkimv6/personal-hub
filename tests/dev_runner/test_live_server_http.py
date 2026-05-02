"""실서버(localhost:8001) 직접 호출 통합 테스트

이 파일의 테스트는 실제 서버가 기동된 상태에서만 의미 있다.
실서버 미기동 시 pytest.skip()으로 자동 건너뜀.

[MUTATING] restart-frontend tests in this file restart live frontend services.
Run them sequentially; concurrent restart validation can trip the frontend lock.

사용법:
    pytest -m http_live -v          # 실서버 기동 상태에서 실행
    pytest -m "not http_live" -v    # 기본 실행 (이 파일 제외)
"""
import subprocess
import sys
import time
from pathlib import Path

import pytest
import httpx

from app.core.runtime_fingerprint import build_runtime_fingerprint_snapshot
from tests.helpers.restart_frontend_validation import restart_frontend_failure_context

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"
PUBLIC_FRONTEND_URL = "http://127.0.0.2:6100"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BROWSER_WORKERS_SCRIPT = PROJECT_ROOT / "scripts" / "services" / "browser_workers.py"


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


def _wait_for_http_200(url: str, *, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + max(timeout_seconds, 1.0)
    last_error: str | None = None
    while time.time() <= deadline:
        try:
            response = httpx.get(url, timeout=5)
            if response.status_code == 200:
                return
            last_error = f"unexpected status: {response.status_code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    pytest.fail(f"HTTP endpoint did not recover: {url} ({last_error})")


def test_live_health_check():
    """R: 실서버 루트 엔드포인트 200 응답 확인 (서버 기동 여부 검증)"""
    try:
        resp = httpx.get(f"{BASE_URL}/", timeout=5)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")
    assert resp.status_code == 200


def test_live_runners_endpoint():
    """R: /api/v1/dev-runner/runners 엔드포인트 200 응답 + JSON 리스트 확인"""
    try:
        resp = httpx.get(f"{BASE_URL}/api/v1/dev-runner/runners", timeout=5)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_live_liveness_endpoint():
    """R: /api/v1/system/liveness → 200 + status='ok' (merge-test readiness probe, Redis/DB 무관)"""
    try:
        resp = httpx.get(f"{BASE_URL}/api/v1/system/liveness", timeout=5)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"


def test_live_runtime_fingerprint_endpoint():
    """R: /api/v1/system/runtime-fingerprint 엔드포인트 200 응답 + 진단 필드 확인"""
    try:
        resp = httpx.get(f"{BASE_URL}/api/v1/system/runtime-fingerprint", timeout=5)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")
    assert resp.status_code == 200
    data = resp.json()
    expected = build_runtime_fingerprint_snapshot()
    assert "runtime_fingerprint" in data
    assert "source_fingerprint" in data
    assert isinstance(data.get("source_files"), list)
    assert data["source_fingerprint"] == expected["source_fingerprint"]


def test_live_restart_frontend_admin_returns_exit_zero_and_recovers_liveness():
    """R: admin restart live smoke는 exit 0과 liveness 회복을 함께 보장해야 한다."""
    result = _run_restart_frontend()
    assert result.returncode == 0, restart_frontend_failure_context(result)
    _wait_for_http_200(f"{BASE_URL}/api/v1/system/liveness")


def test_live_restart_frontend_public_returns_exit_zero_and_recovers_public_preview():
    """R: public restart live smoke는 exit 0과 public preview 회복을 함께 보장해야 한다."""
    result = _run_restart_frontend("--public")
    assert result.returncode == 0, restart_frontend_failure_context(result)
    _wait_for_http_200(PUBLIC_FRONTEND_URL)
    _wait_for_http_200(f"{BASE_URL}/api/v1/system/liveness")
