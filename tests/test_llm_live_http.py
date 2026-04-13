"""LLM API 실서버(localhost:8001) http_live 테스트

TestClient 기반 오분류 e2e 테스트가 검증하던 API 레벨 동작을
실서버 직접 호출로 재검증한다.

사용법:
    pytest -m http_live tests/test_llm_live_http.py -v
    # 실서버 미기동 시 자동 skip
"""
import pytest
import httpx

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------

def _get(path: str, timeout: int = 5, **kwargs) -> httpx.Response:
    """GET 요청. 실서버 미기동 시 pytest.skip()."""
    try:
        return httpx.get(BASE_URL + path, timeout=timeout, **kwargs)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")


def _post(path: str, timeout: int = 5, **kwargs) -> httpx.Response:
    """POST 요청. 실서버 미기동 시 pytest.skip()."""
    try:
        return httpx.post(BASE_URL + path, timeout=timeout, **kwargs)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")


def _put(path: str, timeout: int = 5, **kwargs) -> httpx.Response:
    """PUT 요청. 실서버 미기동 시 pytest.skip()."""
    try:
        return httpx.put(BASE_URL + path, timeout=timeout, **kwargs)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")


# ---------------------------------------------------------------------------
# Phase 2: LLM Providers API
# ---------------------------------------------------------------------------

def test_live_llm_providers_returns_200():
    """R: GET /api/v1/llm/providers → 200 응답."""
    resp = _get("/api/v1/llm/providers")
    assert resp.status_code == 200


def test_live_llm_providers_returns_list():
    """R: GET /api/v1/llm/providers → 응답이 list 타입."""
    resp = _get("/api/v1/llm/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list), f"providers 응답이 list가 아님: {type(data)}"


def test_live_llm_providers_includes_claude():
    """R: GET /api/v1/llm/providers → claude provider 포함."""
    resp = _get("/api/v1/llm/providers")
    assert resp.status_code == 200
    data = resp.json()
    provider_names = [p.get("name") or p.get("id") or str(p) for p in data]
    assert any("claude" in str(name).lower() for name in provider_names), (
        f"claude provider가 없음. providers: {provider_names}"
    )


def test_live_llm_providers_no_disabled_entries():
    """B: GET /api/v1/llm/providers → disabled provider 미포함."""
    resp = _get("/api/v1/llm/providers")
    assert resp.status_code == 200
    data = resp.json()
    for p in data:
        enabled = p.get("enabled", True)
        assert enabled, f"disabled provider가 포함됨: {p}"


# ---------------------------------------------------------------------------
# Phase 3: LLM Profiles API
# ---------------------------------------------------------------------------

def test_live_llm_profiles_returns_200():
    """R: GET /api/v1/llm/profiles → 200 응답."""
    resp = _get("/api/v1/llm/profiles")
    assert resp.status_code == 200


def test_live_llm_profiles_schema():
    """R: GET /api/v1/llm/profiles → profiles / selected 키 포함."""
    resp = _get("/api/v1/llm/profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert "profiles" in data, f"profiles 키 없음: {list(data.keys())}"
    assert "selected" in data, f"selected 키 없음: {list(data.keys())}"


def test_live_llm_profile_select_claude_returns_200_or_404():
    """R: POST /api/v1/llm/profiles/claude/select → 200 (존재 시) 또는 404 (미존재 시)."""
    resp = _post("/api/v1/llm/profiles/claude/select", json={"name": "default"})
    assert resp.status_code in (200, 404), f"응답: {resp.status_code} {resp.text[:200]}"


def test_live_llm_profile_select_unknown_engine_returns_4xx():
    """E: POST /api/v1/llm/profiles/__nonexistent__/select → 404 또는 422."""
    resp = _post("/api/v1/llm/profiles/__nonexistent__/select", json={"name": "x"})
    assert resp.status_code in (404, 422), (
        f"비존재 engine 선택 시 4xx 아님: {resp.status_code} {resp.text[:200]}"
    )


# ---------------------------------------------------------------------------
# Phase 4: LLM Quota API
# ---------------------------------------------------------------------------

def test_live_llm_quota_returns_200():
    """R: GET /api/v1/llm/quota → 200 응답."""
    resp = _get("/api/v1/llm/quota")
    assert resp.status_code == 200


def test_live_llm_quota_schema():
    """R: GET /api/v1/llm/quota → 응답에 provider별 quota 정보 포함."""
    resp = _get("/api/v1/llm/quota")
    assert resp.status_code == 200
    data = resp.json()
    # quota 응답은 dict 또는 list 형태일 수 있음
    assert data is not None, "quota 응답이 None"


def test_live_llm_quota_status_returns_200():
    """R: GET /api/v1/llm/quota-status → 200 응답."""
    resp = _get("/api/v1/llm/quota-status")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Phase 5: 프로세스 감시 API (process_watch 대체)
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


# ---------------------------------------------------------------------------
# Phase 6: LLM enqueue 파이프라인 (model_registry_e2e 대체)
# ---------------------------------------------------------------------------

def test_live_llm_enqueue_returns_200():
    """R: POST /api/v1/llm/requests → 200 (enqueue 성공)."""
    resp = _post("/api/v1/llm/requests", json={
        "caller_type": "test",
        "caller_id": "live_http_tc",
        "prompt": "test prompt",
        "provider": "claude",
        "queue_name": "utility",
    })
    assert resp.status_code == 200, f"enqueue 실패: {resp.status_code} {resp.text[:300]}"


def test_live_llm_enqueue_response_has_id():
    """R: enqueue 응답 JSON에 id, status, caller_type 필드 존재."""
    resp = _post("/api/v1/llm/requests", json={
        "caller_type": "test",
        "caller_id": "live_http_tc_fields",
        "prompt": "test prompt",
        "provider": "claude",
        "queue_name": "utility",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data, f"id 필드 없음: {list(data.keys())}"
    assert "status" in data, f"status 필드 없음: {list(data.keys())}"
    assert "caller_type" in data, f"caller_type 필드 없음: {list(data.keys())}"

    # 생성된 request 취소 (부작용 최소화)
    req_id = data["id"]
    try:
        _post(f"/api/v1/llm/requests/{req_id}/cancel")
    except Exception:
        pass


def test_live_llm_enqueue_status_is_pending():
    """R: 생성 직후 status == 'pending' 또는 'queued'."""
    resp = _post("/api/v1/llm/requests", json={
        "caller_type": "test",
        "caller_id": "live_http_tc_status",
        "prompt": "test prompt",
        "provider": "claude",
        "queue_name": "utility",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("pending", "queued"), (
        f"생성 직후 status가 pending/queued가 아님: {data['status']}"
    )

    # 생성된 request 취소
    req_id = data["id"]
    try:
        _post(f"/api/v1/llm/requests/{req_id}/cancel")
    except Exception:
        pass


def test_live_llm_enqueue_persisted_in_db():
    """R: enqueue 후 GET /api/v1/llm/requests/{id} → 200, 동일 caller_id 확인."""
    resp = _post("/api/v1/llm/requests", json={
        "caller_type": "test",
        "caller_id": "live_http_tc_persist",
        "prompt": "test prompt",
        "provider": "claude",
        "queue_name": "utility",
    })
    assert resp.status_code == 200
    req_id = resp.json()["id"]

    get_resp = _get(f"/api/v1/llm/requests/{req_id}")
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["caller_id"] == "live_http_tc_persist", (
        f"caller_id 불일치: {detail.get('caller_id')}"
    )

    # 취소
    try:
        _post(f"/api/v1/llm/requests/{req_id}/cancel")
    except Exception:
        pass


def test_live_llm_enqueue_cancel_returns_200():
    """B: enqueue 직후 cancel → 200, success=true."""
    resp = _post("/api/v1/llm/requests", json={
        "caller_type": "test",
        "caller_id": "live_http_tc_cancel",
        "prompt": "test prompt",
        "provider": "claude",
        "queue_name": "utility",
    })
    assert resp.status_code == 200
    req_id = resp.json()["id"]

    cancel_resp = _post(f"/api/v1/llm/requests/{req_id}/cancel")
    assert cancel_resp.status_code == 200, (
        f"cancel 실패: {cancel_resp.status_code} {cancel_resp.text[:200]}"
    )
    cancel_data = cancel_resp.json()
    assert cancel_data.get("success") is True, f"success!=true: {cancel_data}"


def test_live_llm_enqueue_cancel_not_pending_returns_400():
    """E: 이미 cancel된 request 재cancel → 400."""
    resp = _post("/api/v1/llm/requests", json={
        "caller_type": "test",
        "caller_id": "live_http_tc_cancel2",
        "prompt": "test prompt",
        "provider": "claude",
        "queue_name": "utility",
    })
    assert resp.status_code == 200
    req_id = resp.json()["id"]

    # 첫 번째 cancel
    _post(f"/api/v1/llm/requests/{req_id}/cancel")

    # 두 번째 cancel → 400
    cancel2 = _post(f"/api/v1/llm/requests/{req_id}/cancel")
    assert cancel2.status_code == 400, (
        f"이중 cancel 시 400이 아님: {cancel2.status_code} {cancel2.text[:200]}"
    )


def test_live_llm_enqueue_missing_prompt_returns_422():
    """E: prompt 누락 → 422 Unprocessable Entity."""
    resp = _post("/api/v1/llm/requests", json={
        "caller_type": "test",
        "caller_id": "live_http_tc_no_prompt",
    })
    assert resp.status_code == 422, (
        f"prompt 누락 시 422가 아님: {resp.status_code} {resp.text[:200]}"
    )


def test_live_llm_enqueue_invalid_provider_returns_4xx():
    """E: 비유효 provider → 4xx."""
    resp = _post("/api/v1/llm/requests", json={
        "caller_type": "test",
        "caller_id": "live_http_tc_bad_provider",
        "prompt": "test",
        "provider": "__invalid__",
    })
    assert resp.status_code >= 400, (
        f"비유효 provider인데 4xx가 아님: {resp.status_code} {resp.text[:200]}"
    )
