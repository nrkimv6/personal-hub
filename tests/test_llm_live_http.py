"""LLM API 실서버(localhost:8001) http_live 테스트

TestClient 기반 오분류 e2e 테스트가 검증하던 API 레벨 동작을
실서버 직접 호출로 재검증한다.

사용법:
    pytest -m http_live tests/test_llm_live_http.py -v
    # 실서버 미기동 시 자동 skip
"""
import pytest
import httpx
import time
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import text

from app.database import SessionLocal
from app.models.writing import GeneratedWriting
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.reports.models.generated_report import GeneratedReport

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"
CONNECT_RETRY_SECONDS = 45
CONNECT_RETRY_INTERVAL = 1.0


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------

def _request_with_connect_retry(method: str, path: str, timeout: int = 5, **kwargs) -> httpx.Response:
    """실서버 재시작 공백을 흡수하며 요청한다."""
    deadline = time.monotonic() + CONNECT_RETRY_SECONDS
    last_error: httpx.ConnectError | None = None

    while time.monotonic() < deadline:
        try:
            return httpx.request(method, BASE_URL + path, timeout=timeout, **kwargs)
        except httpx.ConnectError as exc:
            last_error = exc
            time.sleep(CONNECT_RETRY_INTERVAL)

    detail = f": {last_error}" if last_error else ""
    pytest.fail(f"실서버 미기동 또는 재시작 장기화 — localhost:8001 연결 불가{detail}")


def _get(path: str, timeout: int = 5, **kwargs) -> httpx.Response:
    """GET 요청. 실서버 재시작 공백은 짧게 재시도한다."""
    return _request_with_connect_retry("GET", path, timeout=timeout, **kwargs)


def _post(path: str, timeout: int = 5, **kwargs) -> httpx.Response:
    """POST 요청. 실서버 재시작 공백은 짧게 재시도한다."""
    return _request_with_connect_retry("POST", path, timeout=timeout, **kwargs)


def _put(path: str, timeout: int = 5, **kwargs) -> httpx.Response:
    """PUT 요청. 실서버 재시작 공백은 짧게 재시도한다."""
    return _request_with_connect_retry("PUT", path, timeout=timeout, **kwargs)


def _seed_failed_live_request(caller_id: str) -> int:
    """실서버가 보는 DB에 failed 요청 1건을 직접 삽입한다."""
    db = SessionLocal()
    try:
        request = LLMRequest(
            caller_type="test",
            caller_id=caller_id,
            prompt="live batch retry test",
            status="failed",
            error_message="seeded failure",
        )
        db.add(request)
        db.commit()
        db.refresh(request)
        return request.id
    finally:
        db.close()


def _delete_live_request(request_id: int) -> None:
    """실서버가 보는 DB에서 테스트 요청을 정리한다."""
    db = SessionLocal()
    try:
        request = db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
        if request is not None:
            db.delete(request)
            db.commit()
    finally:
        db.close()


def _seed_old_completed_request_with_children(caller_id: str) -> tuple[int, int, int]:
    """hard delete cleanup 대상이 되는 오래된 completed 요청과 자식 row를 삽입한다."""
    db = SessionLocal()
    try:
        processed_at = datetime.now() - timedelta(days=31)
        request = LLMRequest(
            caller_type="test_cleanup_history_hard_delete",
            caller_id=caller_id,
            prompt="live cleanup hard delete test",
            status="completed",
            result='{"ok": true}',
            requested_at=processed_at,
            processed_at=processed_at,
            requested_by="pytest",
            request_source="http_live",
        )
        db.add(request)
        db.flush()
        db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('generated_writings','id'), "
                "COALESCE((SELECT MAX(id) FROM generated_writings), 1), true)"
            )
        )
        db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('generated_reports','id'), "
                "COALESCE((SELECT MAX(id) FROM generated_reports), 1), true)"
            )
        )
        writing = GeneratedWriting(
            task_type="random",
            content="live cleanup generated writing",
            llm_request_id=request.id,
        )
        report = GeneratedReport(
            report_type="live_cleanup",
            period_start=processed_at,
            period_end=processed_at,
            title="live cleanup report",
            content="live cleanup generated report",
            llm_request_id=request.id,
        )
        db.add_all([writing, report])
        db.commit()
        return request.id, writing.id, report.id
    finally:
        db.close()


def _cleanup_live_child_rows(writing_id: int, report_id: int) -> None:
    """테스트가 중간 실패해도 synthetic child row만 정리한다."""
    db = SessionLocal()
    try:
        db.query(GeneratedWriting).filter(GeneratedWriting.id == writing_id).delete()
        db.query(GeneratedReport).filter(GeneratedReport.id == report_id).delete()
        db.commit()
    finally:
        db.close()


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
# LLM Bootstrap API
# ---------------------------------------------------------------------------

def test_live_llm_bootstrap_returns_200_and_serialized_items():
    """R: GET /api/v1/llm/bootstrap → 200 + 직렬화된 list shape."""
    resp = _get("/api/v1/llm/bootstrap?status=completed&page=1&page_size=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "list" in data
    assert "items" in data["list"]
    assert "stats" in data
    assert "worker_status" in data
    for item in data["list"]["items"]:
        if item.get("result") is not None:
            assert not isinstance(item["result"], str), f"result가 문자열로 남음: {item}"
        if item.get("cli_options") is not None:
            assert not isinstance(item["cli_options"], str), f"cli_options가 문자열로 남음: {item}"


def test_cleanup_history_http_live_openapi_default_is_soft_delete():
    """R: live OpenAPI 계약에서 cleanup history hard_delete 기본값은 false."""
    resp = _get("/openapi.json", timeout=10)
    assert resp.status_code == 200
    operation = resp.json()["paths"]["/api/v1/llm/cleanup/history"]["post"]
    hard_delete_param = next(
        param for param in operation["parameters"] if param["name"] == "hard_delete"
    )

    assert hard_delete_param["schema"]["default"] is False


def test_cleanup_history_hard_delete_http_live_no_fk_violation():
    """R: live hard delete cleanup succeeds and preserves child rows with NULL FK."""
    caller_id = f"cleanup-hard-delete-{uuid4()}"
    request_id, writing_id, report_id = _seed_old_completed_request_with_children(caller_id)
    try:
        resp = _post("/api/v1/llm/cleanup/history?days=30&hard_delete=true", timeout=30)
        assert resp.status_code == 200, resp.text[:500]

        db = SessionLocal()
        try:
            assert db.query(LLMRequest).filter(LLMRequest.id == request_id).first() is None
            writing = db.query(GeneratedWriting).filter(GeneratedWriting.id == writing_id).one()
            report = db.query(GeneratedReport).filter(GeneratedReport.id == report_id).one()
            assert writing.llm_request_id is None
            assert report.llm_request_id is None
            assert writing.content == "live cleanup generated writing"
            assert report.content == "live cleanup generated report"
        finally:
            db.close()
    finally:
        _delete_live_request(request_id)
        _cleanup_live_child_rows(writing_id, report_id)


# ---------------------------------------------------------------------------
# Phase 5: LLM enqueue 파이프라인 (model_registry_e2e 대체)
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


def test_live_llm_enqueue_cancel_returns_200_or_400():
    """B: enqueue 직후 cancel → 200, 경합 시 400(not pending)."""
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
    assert cancel_resp.status_code in (200, 400), (
        f"cancel 응답이 예상 범위를 벗어남: {cancel_resp.status_code} {cancel_resp.text[:200]}"
    )
    if cancel_resp.status_code == 200:
        cancel_data = cancel_resp.json()
        assert cancel_data.get("success") is True, f"success!=true: {cancel_data}"
    else:
        assert cancel_resp.json().get("detail") == "Cannot cancel this request (not pending)"


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


def test_live_llm_batch_retry_returns_200_for_failed_requests():
    """R: POST /api/v1/llm/requests/batch/retry → failed 요청을 pending으로 전환."""
    caller_id = f"live_http_batch_retry_{uuid4().hex}"
    request_id = _seed_failed_live_request(caller_id)

    try:
        resp = _post("/api/v1/llm/requests/batch/retry", json={"request_ids": [request_id]})
        assert resp.status_code == 200, f"batch retry 실패: {resp.status_code} {resp.text[:200]}"
        body = resp.json()
        assert body["success"] == 1, body
        assert body["skipped"] == 0, body

        db = SessionLocal()
        try:
            request = db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
            assert request is not None
            assert request.status == "pending"
        finally:
            db.close()
    finally:
        _delete_live_request(request_id)


def test_live_llm_retry_unknown_numeric_id_returns_400_not_422():
    """E: GET/POST numeric retry path는 422 path parsing error가 아니라 400 business error."""
    resp = _post("/api/v1/llm/requests/99999999/retry")
    assert resp.status_code == 400, f"unknown retry가 400이 아님: {resp.status_code} {resp.text[:200]}"
    assert resp.json()["detail"] == "Cannot retry this request"
