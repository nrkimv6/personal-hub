"""
LLM Request PATCH API 테스트

PATCH /api/v1/llm/requests/{id} 엔드포인트 검증.
- pending/failed 상태만 수정 허용
- cli_options, prompt 필드 부분 업데이트 지원
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.routes.llm_routes import router as llm_router

app = FastAPI()
app.include_router(llm_router)


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def cleanup(test_db_session):
    test_db_session.query(LLMRequest).delete()
    test_db_session.commit()
    yield
    test_db_session.query(LLMRequest).delete()
    test_db_session.commit()


@pytest.fixture
def pending_request(test_db_session):
    req = LLMRequest(
        caller_type="test",
        caller_id="test-pending-001",
        prompt="/plan test",
        status="pending",
        requested_by="api",
        queue_name="system",
        cli_options=json.dumps({"cwd": "D:/work/project/service/wtools", "parse_json": False}),
    )
    test_db_session.add(req)
    test_db_session.commit()
    test_db_session.refresh(req)
    return req


@pytest.fixture
def failed_request(test_db_session):
    req = LLMRequest(
        caller_type="test",
        caller_id="test-failed-001",
        prompt="/plan test failed",
        status="failed",
        requested_by="api",
        queue_name="system",
        error_message="Some error",
        cli_options=json.dumps({"cwd": "D:/work/project/service/wtools"}),
    )
    test_db_session.add(req)
    test_db_session.commit()
    test_db_session.refresh(req)
    return req


@pytest.fixture
def completed_request(test_db_session):
    req = LLMRequest(
        caller_type="test",
        caller_id="test-completed-001",
        prompt="/plan test completed",
        status="completed",
        requested_by="api",
        queue_name="system",
    )
    test_db_session.add(req)
    test_db_session.commit()
    test_db_session.refresh(req)
    return req


class TestUpdateRequestCliOptions:
    """PATCH /api/v1/llm/requests/{id} — cli_options 수정 테스트."""

    def test_update_request_cli_options_RIGHT(self, client, pending_request):
        """pending 요청 cli_options.cwd 변경 → 응답 cli_options.cwd 일치."""
        resp = client.patch(
            f"/api/v1/llm/requests/{pending_request.id}",
            json={"cli_options": {"cwd": "D:/work/project/tools/monitor-page", "parse_json": False}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cli_options"]["cwd"] == "D:/work/project/tools/monitor-page"

    def test_update_request_prompt_RIGHT(self, client, pending_request):
        """pending 요청 prompt 변경 → 응답 prompt 일치."""
        resp = client.patch(
            f"/api/v1/llm/requests/{pending_request.id}",
            json={"prompt": "/plan new prompt text"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["prompt"] == "/plan new prompt text"

    def test_update_failed_request_RIGHT(self, client, failed_request):
        """failed 요청도 cli_options 수정 가능."""
        resp = client.patch(
            f"/api/v1/llm/requests/{failed_request.id}",
            json={"cli_options": {"cwd": "D:/work/project/tools/monitor-page"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cli_options"]["cwd"] == "D:/work/project/tools/monitor-page"

    def test_update_completed_request_ERROR(self, client, completed_request):
        """completed 상태 → 400 응답."""
        resp = client.patch(
            f"/api/v1/llm/requests/{completed_request.id}",
            json={"cli_options": {"cwd": "D:/work/project/tools/monitor-page"}},
        )
        assert resp.status_code == 400
        assert "completed" in resp.json()["detail"]

    def test_update_nonexistent_request_ERROR(self, client):
        """존재하지 않는 ID → 404 응답."""
        resp = client.patch(
            "/api/v1/llm/requests/99999",
            json={"cli_options": {"cwd": "D:/work/project/tools/monitor-page"}},
        )
        assert resp.status_code == 404

    def test_update_request_partial_BOUNDARY(self, client, pending_request):
        """cli_options=None만 전달 시 기존 prompt 보존."""
        original_prompt = pending_request.prompt
        resp = client.patch(
            f"/api/v1/llm/requests/{pending_request.id}",
            json={"cli_options": {"cwd": "D:/new/path"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        # prompt는 변경되지 않아야 함
        assert data["prompt"] == original_prompt
        # cli_options는 변경됨
        assert data["cli_options"]["cwd"] == "D:/new/path"
