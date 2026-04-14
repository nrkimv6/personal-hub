"""프로세스 감시 실서버(localhost:8001) http_live 테스트

실서버에서만 의미 있는 process-watch 엔드포인트를 검증한다.

사용법:
    pytest -m http_live tests/test_process_watch_live_http.py -v
"""
import pytest
import httpx

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"


def _get(path: str, timeout: int = 5, **kwargs) -> httpx.Response:
    """GET 요청. 실서버 미기동 시 pytest.fail()."""
    try:
        return httpx.get(BASE_URL + path, timeout=timeout, **kwargs)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")


# ---------------------------------------------------------------------------
# Process Watch API
# ---------------------------------------------------------------------------

def test_live_process_watch_latest_returns_200():
    """R: GET /api/v1/system/process-watch/latest → 200."""
    resp = _get("/api/v1/system/process-watch/latest", timeout=30)
    assert resp.status_code == 200


def test_live_process_watch_latest_schema():
    """R: /api/v1/system/process-watch/latest 응답에 items, source, item_count 필드 존재."""
    resp = _get("/api/v1/system/process-watch/latest", timeout=30)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data, f"items 키 없음: {list(data.keys())}"
    assert "source" in data, f"source 키 없음: {list(data.keys())}"
    assert "item_count" in data, f"item_count 키 없음: {list(data.keys())}"


def test_live_process_watch_latest_items_or_empty():
    """B: 서버 기동 직후 스냅샷 미생성 시 items=[], item_count=0도 정상."""
    resp = _get("/api/v1/system/process-watch/latest", timeout=30)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["items"], list), "items가 list가 아님"
    assert isinstance(data["item_count"], int), "item_count가 int가 아님"


def test_live_process_watch_history_returns_200():
    """R: GET /api/v1/system/process-watch/history → 200."""
    resp = _get("/api/v1/system/process-watch/history")
    assert resp.status_code == 200


def test_live_process_watch_history_schema():
    """R: /api/v1/system/process-watch/history 응답에 total, items 필드 존재."""
    resp = _get("/api/v1/system/process-watch/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data, f"total 키 없음: {list(data.keys())}"
    assert "items" in data, f"items 키 없음: {list(data.keys())}"
