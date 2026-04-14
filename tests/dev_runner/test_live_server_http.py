"""실서버(localhost:8001) 직접 호출 통합 테스트

이 파일의 테스트는 실제 서버가 기동된 상태에서만 의미 있다.
실서버 미기동 시 pytest.skip()으로 자동 건너뜀.

사용법:
    pytest -m http_live -v          # 실서버 기동 상태에서 실행
    pytest -m "not http_live" -v    # 기본 실행 (이 파일 제외)
"""
import pytest
import httpx

from app.core.runtime_fingerprint import build_runtime_fingerprint_snapshot

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"


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
