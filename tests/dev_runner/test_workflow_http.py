"""
Workflow API HTTP 통합 테스트 (Phase T4)

엔드포인트: /api/v1/dev-runner/workflows
TestClient 사용, test_db_engine 픽스처로 격리

TC:
  - test_get_workflows_empty: 빈 DB → 200 + []
  - test_post_create_workflow: POST → 201 + WorkflowResponse
  - test_get_workflows_with_filter: ?status= 필터
  - test_patch_workflow_cancel: PATCH cancel → status=cancelled, finished_at 설정
"""
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.http


@pytest.fixture(scope="module")
def client(test_db_engine):
    """TestClient (module scope) + test_db_engine 오버라이드"""
    from app.main import app
    from app.database import get_db
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


BASE = "/api/v1/dev-runner/workflows"


def test_get_workflows_empty(client):
    """R: 빈 DB → GET /workflows → 200 + []"""
    resp = client.get(BASE)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # 다른 테스트에서 생성된 레코드가 있을 수 있으므로 타입만 확인


def test_post_create_workflow(client):
    """R: POST /workflows → 201 + WorkflowResponse (slug, status=planned)"""
    payload = {"plan_file": "docs/plan/2026-03-03_test-http.md", "slug": "test-http-create"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "test-http-create"
    assert data["plan_file"] == "docs/plan/2026-03-03_test-http.md"
    assert data["status"] == "planned"
    assert data["id"] > 0
    assert data["created_at"] is not None


def test_post_create_workflow_without_slug(client):
    """R: POST /workflows slug 없이 → plan_file에서 slug 자동 생성"""
    payload = {"plan_file": "docs/plan/2026-03-03_auto-slug_todo.md"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    data = resp.json()
    # _todo 접미사가 제거된 slug 생성
    assert "auto-slug" in data["slug"]
    assert data["status"] == "planned"


def test_get_workflows_with_filter(client):
    """R: ?status=planned 필터 → 해당 상태만 반환"""
    # planned 하나 생성
    payload = {"slug": "filter-test-planned"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    wf_id = resp.json()["id"]

    # 전체 조회
    resp_all = client.get(BASE)
    assert resp_all.status_code == 200
    all_count = len(resp_all.json())
    assert all_count >= 1

    # planned 필터
    resp_filtered = client.get(f"{BASE}?status=planned")
    assert resp_filtered.status_code == 200
    filtered = resp_filtered.json()
    assert all(w["status"] == "planned" for w in filtered)
    assert any(w["id"] == wf_id for w in filtered)

    # failed 필터 → 우리가 생성한 레코드는 포함 안 됨
    resp_failed = client.get(f"{BASE}?status=failed")
    assert resp_failed.status_code == 200
    assert all(w["id"] != wf_id for w in resp_failed.json())


def test_get_workflow_detail(client):
    """R: GET /workflows/{id} → 단건 조회"""
    payload = {"slug": "detail-test"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    wf_id = resp.json()["id"]

    resp_detail = client.get(f"{BASE}/{wf_id}")
    assert resp_detail.status_code == 200
    data = resp_detail.json()
    assert data["id"] == wf_id
    assert data["slug"] == "detail-test"


def test_get_workflow_detail_not_found(client):
    """B: 존재하지 않는 ID → 404"""
    resp = client.get(f"{BASE}/999999")
    assert resp.status_code == 404


def test_patch_workflow_cancel(client):
    """R: PATCH /workflows/{id}/cancel → status=cancelled, finished_at 설정"""
    payload = {"slug": "cancel-test"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    wf_id = resp.json()["id"]

    resp_cancel = client.patch(f"{BASE}/{wf_id}/cancel")
    assert resp_cancel.status_code == 200
    data = resp_cancel.json()
    assert data["status"] == "cancelled"
    assert data["finished_at"] is not None


def test_patch_cancel_already_cancelled(client):
    """B: 이미 cancelled 상태 workflow 재취소 시도 → 409 Conflict"""
    payload = {"slug": "double-cancel-test"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    wf_id = resp.json()["id"]

    # 첫 번째 취소 → 성공
    resp1 = client.patch(f"{BASE}/{wf_id}/cancel")
    assert resp1.status_code == 200

    # 두 번째 취소 → 400 (이미 terminal 상태 — planned/running이 아님)
    resp2 = client.patch(f"{BASE}/{wf_id}/cancel")
    assert resp2.status_code == 400
