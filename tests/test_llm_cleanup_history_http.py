"""LLM cleanup history HTTP contract tests."""

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.writing import GeneratedWriting
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.routes.llm_routes import router as llm_router
from app.modules.reports.models.generated_report import GeneratedReport

pytestmark = pytest.mark.http

app = FastAPI()
app.include_router(llm_router)


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def cleanup_rows(test_db_session):
    test_db_session.query(GeneratedReport).delete()
    test_db_session.query(GeneratedWriting).delete()
    test_db_session.query(LLMRequest).delete()
    test_db_session.commit()
    yield
    test_db_session.query(GeneratedReport).delete()
    test_db_session.query(GeneratedWriting).delete()
    test_db_session.query(LLMRequest).delete()
    test_db_session.commit()


def _old_completed_request(test_db_session, caller_id: str = "cleanup-http") -> LLMRequest:
    old_time = datetime.now() - timedelta(days=8)
    request = LLMRequest(
        caller_type="test_cleanup_history_http",
        caller_id=caller_id,
        prompt="cleanup history http",
        status="completed",
        requested_at=old_time - timedelta(hours=1),
        processed_at=old_time,
    )
    test_db_session.add(request)
    test_db_session.commit()
    test_db_session.refresh(request)
    return request


def test_cleanup_history_R_default_soft_delete_http(client, test_db_session):
    request = _old_completed_request(test_db_session, "default")

    response = client.post("/api/v1/llm/cleanup/history", params={"days": 7})

    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    persisted = test_db_session.get(LLMRequest, request.id)
    assert persisted is not None
    assert persisted.deleted_at is not None


def test_cleanup_history_B_hard_delete_true_http(client, test_db_session):
    request = _old_completed_request(test_db_session, "hard-delete")
    request_id = request.id

    response = client.post(
        "/api/v1/llm/cleanup/history",
        params={"days": 7, "hard_delete": "true"},
    )

    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    assert test_db_session.get(LLMRequest, request_id) is None


def test_cleanup_history_R_hard_delete_with_child_rows_after_fk_set_null_http(client, test_db_session):
    request = _old_completed_request(test_db_session, "children")
    generated_writing = GeneratedWriting(
        task_type=GeneratedWriting.TASK_TYPE_MIX,
        content="generated content",
        llm_request_id=request.id,
    )
    generated_report = GeneratedReport(
        report_type="cleanup_test",
        period_start=datetime.now() - timedelta(days=9),
        period_end=datetime.now() - timedelta(days=8),
        content="report content",
        llm_request_id=request.id,
    )
    test_db_session.add_all([generated_writing, generated_report])
    test_db_session.commit()
    writing_id = generated_writing.id
    report_id = generated_report.id

    response = client.post(
        "/api/v1/llm/cleanup/history",
        params={"days": 7, "hard_delete": "true"},
    )

    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    assert test_db_session.get(LLMRequest, request.id) is None
    test_db_session.expire_all()
    assert test_db_session.get(GeneratedWriting, writing_id).llm_request_id is None
    assert test_db_session.get(GeneratedReport, report_id).llm_request_id is None
