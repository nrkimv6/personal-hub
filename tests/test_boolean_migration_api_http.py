"""T5: HTTP 통합 테스트 — boolean 마이그레이션 후 API 엔드포인트 정상 동작 확인
monitor_schedules.is_enabled = true 쿼리 포함 경로가 500 에러 없이 200 반환하는지 검증.

관련 plan: docs/plan/2026-04-11_fix-boolean-column-type-pg-migration.md
실행: main 머지 후 /merge-test 또는 pytest tests/test_boolean_migration_api_http.py
"""
import pytest
import requests

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"


@pytest.fixture(scope="module")
def client():
    """HTTP 클라이언트 — 실행 중인 서버에 직접 요청"""
    return requests.Session()


def _request(client: requests.Session, method: str, path: str, timeout: int = 10, **kwargs):
    """실서버 요청 헬퍼. 미기동이면 즉시 실패."""
    try:
        return client.request(method, f"{BASE_URL}{path}", timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        pytest.fail(f"실서버 미기동 — localhost:8001 연결 불가: {exc}")


def _get(client: requests.Session, path: str, timeout: int = 10, **kwargs):
    return _request(client, "GET", path, timeout=timeout, **kwargs)


def _post(client: requests.Session, path: str, timeout: int = 10, **kwargs):
    return _request(client, "POST", path, timeout=timeout, **kwargs)


@pytest.fixture(scope="module")
def paused_state(client):
    """paused_at 검증용으로 일시중지 상태를 만들고 종료 시 원복한다."""
    status_resp = _get(client, "/api/v1/worker/status")
    assert status_resp.status_code == 200, (
        f"worker/status 사전 조회 실패: {status_resp.status_code} {status_resp.text[:200]}"
    )
    should_resume = not bool(status_resp.json().get("global_pause"))

    if should_resume:
        pause_resp = _post(client, "/api/v1/worker/pause")
        assert pause_resp.status_code == 200, (
            f"worker/pause 실패: {pause_resp.status_code} {pause_resp.text[:200]}"
        )
        assert pause_resp.json().get("success") is True, pause_resp.text

    try:
        yield
    finally:
        if should_resume:
            resume_resp = _post(client, "/api/v1/worker/resume")
            assert resume_resp.status_code == 200, (
                f"worker/resume 실패: {resume_resp.status_code} {resume_resp.text[:200]}"
            )
            resume_data = resume_resp.json()
            if not resume_data.get("success"):
                assert "이미 실행 중" in resume_data.get("message", ""), resume_resp.text


def test_dashboard_unified_200_after_migration(client):
    """T5: GET /api/v1/dashboard/unified → 200 OK
    monitor_schedules.is_enabled = true 쿼리 포함 — 마이그레이션 전 integer = boolean 에러로 500 발생했을 경로
    """
    resp = _get(client, "/api/v1/dashboard/unified")
    assert resp.status_code == 200, (
        f"dashboard/unified 500 에러: {resp.status_code} {resp.text[:200]}"
    )


def test_system_status_200_after_migration(client):
    """T5: GET /api/v1/system/status → 200 OK
    monitor_schedules.is_enabled 카운트 쿼리 포함
    """
    resp = _get(client, "/api/v1/system/status")
    assert resp.status_code == 200, (
        f"system/status 500 에러: {resp.status_code} {resp.text[:200]}"
    )


def test_worker_status_200_after_migration(client):
    """T5: GET /api/v1/worker/status → 200 OK
    is_enabled = true 쿼리 포함
    """
    resp = _get(client, "/api/v1/worker/status")
    assert resp.status_code == 200, (
        f"worker/status 500 에러: {resp.status_code} {resp.text[:200]}"
    )


def test_worker_status_200_schema_after_fix(client):
    """T5: GET /api/v1/worker/status → 200 + 스키마 검증
    수정 후 스키마: started_at 존재, start_time/browser_available 제거됨.
    """
    resp = _get(client, "/api/v1/worker/status")
    assert resp.status_code == 200, (
        f"worker/status 500 에러: {resp.status_code} {resp.text[:200]}"
    )
    data = resp.json()
    assert "started_at" in data, f"started_at 필드가 응답에 없음: {list(data.keys())}"
    assert "start_time" not in data, f"start_time은 제거된 필드인데 응답에 존재: {list(data.keys())}"
    assert "browser_available" not in data, (
        f"browser_available은 제거된 필드인데 응답에 존재: {list(data.keys())}"
    )


def test_worker_status_200_with_paused_at_datetime(client, paused_state):
    """T5: GET /api/v1/worker/status → paused_at datetime이 문자열로 내려와야 함."""
    resp = _get(client, "/api/v1/worker/status")
    assert resp.status_code == 200, (
        f"worker/status 500 에러: {resp.status_code} {resp.text[:200]}"
    )
    data = resp.json()
    assert data["paused_at"] is not None, f"paused_at이 비어 있음: {data}"
    assert isinstance(data["paused_at"], str), f"paused_at이 문자열이 아님: {type(data['paused_at'])}"


def test_system_status_200_with_paused_at_datetime(client, paused_state):
    """T5: GET /api/v1/system/status → paused_at datetime이 문자열로 내려와야 함."""
    resp = _get(client, "/api/v1/system/status")
    assert resp.status_code == 200, (
        f"system/status 500 에러: {resp.status_code} {resp.text[:200]}"
    )
    data = resp.json()
    assert data["paused_at"] is not None, f"paused_at이 비어 있음: {data}"
    assert isinstance(data["paused_at"], str), f"paused_at이 문자열이 아님: {type(data['paused_at'])}"


def test_restart_all_response_includes_worker_running_field(client):
    """T5: POST /api/v1/system/restart-all → worker_running 필드 포함."""
    resp = _post(client, "/api/v1/system/restart-all")
    assert resp.status_code == 200, (
        f"restart-all 응답 실패: {resp.status_code} {resp.text[:200]}"
    )
    data = resp.json()
    assert "worker_running" in data, f"worker_running 필드가 없음: {list(data.keys())}"
    assert isinstance(data["worker_running"], bool), f"worker_running이 bool이 아님: {type(data['worker_running'])}"
