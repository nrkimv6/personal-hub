"""
고아 워크플로우 HTTP 통합 테스트

Phase T4 TC:
  - test_get_orphan_workflows_empty_http: GET /orphans → 200, 빈 리스트
  - test_get_orphan_workflows_found_http: DB에 orphan 있으면 응답에 포함
  - test_reset_workflow_http: PATCH /{id}/reset → 200, status=failed
  - test_reset_workflow_invalid_status_http: status=merged → 400
  - test_reset_all_orphans_http: POST /reset-all-orphans → reset_count
  - test_runner_list_orphan_flag_http: GET /runners 응답에 orphan 필드 존재
"""
import os
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# 테스트 전에 TESTING 환경변수 설정
os.environ["TESTING"] = "1"

from app.main import app
from app.database import get_db
from app.models.workflow import Workflow


@pytest.fixture
def client(test_db_session: Session):
    """TestClient with DB session override"""
    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_redis_empty():
    """Redis mock — sismember always False (모든 runner가 active 아님)"""
    import redis as sync_redis
    with patch("app.modules.dev_runner.routes.workflows.sync_redis") as mock_mod:
        mock_r = mock_mod.from_url.return_value
        mock_r.sismember.return_value = False
        mock_r.close = lambda: None
        yield mock_r


@pytest.fixture
def mock_redis_with_active():
    """Redis mock — specific runner is active"""
    import redis as sync_redis
    with patch("app.modules.dev_runner.routes.workflows.sync_redis") as mock_mod:
        mock_r = mock_mod.from_url.return_value
        mock_r.sismember.side_effect = lambda key, rid: rid == "active-r1"
        mock_r.close = lambda: None
        yield mock_r


def _create_workflow(db: Session, **kwargs) -> Workflow:
    defaults = dict(
        slug=f"test-{datetime.now().timestamp()}",
        status="running",
        runner_id="orphan-r1",
        created_at=datetime.now(),
    )
    defaults.update(kwargs)
    wf = Workflow(**defaults)
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def test_get_orphan_workflows_empty_http(client, mock_redis_empty):
    """GET /orphans → 200, 빈 리스트 (DB에 orphan 없음)"""
    resp = client.get("/api/v1/dev-runner/workflows/orphans")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_orphan_workflows_found_http(client, test_db_session, mock_redis_empty):
    """DB에 running workflow + Redis에 없음 → orphan으로 반환"""
    wf = _create_workflow(test_db_session, slug="orphan-test", runner_id="orphan-r1", status="running")
    resp = client.get("/api/v1/dev-runner/workflows/orphans")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(w["slug"] == "orphan-test" for w in data)


def test_reset_workflow_http(client, test_db_session):
    """PATCH /{id}/reset → 200, status=failed"""
    wf = _create_workflow(test_db_session, slug="reset-test", status="running")
    resp = client.patch(f"/api/v1/dev-runner/workflows/{wf.id}/reset")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error_message"] == "수동 리셋"


def test_reset_workflow_invalid_status_http(client, test_db_session):
    """status=merged → reset 시도 → 400"""
    wf = _create_workflow(test_db_session, slug="merged-test", status="merged")
    resp = client.patch(f"/api/v1/dev-runner/workflows/{wf.id}/reset")
    assert resp.status_code == 400


def test_reset_all_orphans_http(client, test_db_session, mock_redis_empty):
    """POST /reset-all-orphans → orphan 2개 리셋"""
    _create_workflow(test_db_session, slug="orphan-a", runner_id="r-a", status="running")
    _create_workflow(test_db_session, slug="orphan-b", runner_id="r-b", status="merge_pending")
    resp = client.post("/api/v1/dev-runner/workflows/reset-all-orphans")
    assert resp.status_code == 200
    data = resp.json()
    assert data["reset_count"] >= 2


def test_runner_list_orphan_flag_http(client):
    """GET /runners 응답의 각 항목에 orphan 필드 존재 확인"""
    with patch("app.modules.dev_runner.services.executor_service.ExecutorService.get_all_runners", new_callable=AsyncMock) as mock_runners:
        from app.modules.dev_runner.schemas import RunnerListItem
        mock_runners.return_value = [
            RunnerListItem(
                runner_id="test-r1",
                running=False,
                orphan=True,
            )
        ]
        resp = client.get("/api/v1/dev-runner/runners")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert "orphan" in data[0]
        assert data[0]["orphan"] is True
