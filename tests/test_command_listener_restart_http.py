"""
T5 HTTP: command_listener restart HTTP 엔드포인트 검증

POST /api/v1/system/services/infra/command_listener/restart → 200 반환 확인.
GET /api/v1/system/services/workers → command_listener 항목 노출 확인.

live API(localhost:8001) 필요.
/merge-test owner가 main runtime에서만 실행한다.
"""
import pytest
import httpx


BASE = "http://localhost:8001"

pytestmark = pytest.mark.http_live


@pytest.fixture(autouse=True)
def skip_if_api_down():
    try:
        r = httpx.get(f"{BASE}/api/v1/system/liveness", timeout=3.0)
        if r.status_code != 200:
            pytest.skip("live API 미기동 — skip")
    except Exception:
        pytest.skip("live API 미기동 — skip")


class TestCommandListenerRestartHttp:
    """POST /api/v1/system/services/infra/command_listener/restart 계약."""

    def test_right_restart_returns_200(self):
        """restart 엔드포인트가 200을 반환한다."""
        r = httpx.post(
            f"{BASE}/api/v1/system/services/infra/command_listener/restart",
            timeout=10.0,
        )
        assert r.status_code == 200, (
            f"restart 엔드포인트 {r.status_code}: {r.text[:200]}"
        )

    def test_right_workers_list_contains_command_listener(self):
        """GET /api/v1/system/services/workers 에 command_listener 항목이 있다."""
        r = httpx.get(f"{BASE}/api/v1/system/services/workers", timeout=10.0)
        assert r.status_code == 200, f"workers 엔드포인트 {r.status_code}"

        workers = r.json()
        names = [w.get("name") for w in workers if isinstance(w, dict)]
        assert "command_listener" in names, (
            f"command_listener가 workers 목록에 없음. 전체: {names}"
        )

    def test_right_restart_no_error_in_response(self):
        """restart 응답에 error 필드가 없거나 False다."""
        r = httpx.post(
            f"{BASE}/api/v1/system/services/infra/command_listener/restart",
            timeout=10.0,
        )
        assert r.status_code == 200
        body = r.json()
        assert not body.get("error"), f"restart 응답에 error: {body}"
