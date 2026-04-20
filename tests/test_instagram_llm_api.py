"""Instagram LLM API regression tests."""

import json

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.modules.claude_worker.models.llm_request import LLMRequest


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_instagram_llm_post_endpoint_returns_normalized_result(client, test_db_session):
    request = LLMRequest(
        caller_type="instagram",
        caller_id="6041",
        prompt="prompt",
        status="completed",
        result=json.dumps(
            {
                "tag": "이벤트",
                "summary": "원그로브 이벤트",
                "urls": [],
                "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
            },
            ensure_ascii=False,
        ),
    )
    test_db_session.add(request)
    test_db_session.commit()

    response = client.get("/api/v1/instagram/llm/posts/6041")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["result"]["tag"] == "이벤트"
    assert data["result"]["summary"] == "원그로브 이벤트"


def test_instagram_llm_requests_endpoint_filters_non_instagram(client, test_db_session):
    instagram_caller_id = "910001"
    non_instagram_caller_id = "910002"
    test_db_session.add_all(
        [
            LLMRequest(caller_type="instagram", caller_id=instagram_caller_id, prompt="a", status="completed"),
            LLMRequest(caller_type="writing_generate", caller_id=non_instagram_caller_id, prompt="b", status="completed"),
        ]
    )
    test_db_session.commit()

    response = client.get("/api/v1/instagram/llm/requests")
    assert response.status_code == 200
    data = response.json()
    returned_post_ids = {item["post_id"] for item in data["requests"]}
    assert int(instagram_caller_id) in returned_post_ids
    assert int(non_instagram_caller_id) not in returned_post_ids


def test_instagram_llm_post_endpoint_exposes_encoding_mojibake_failure(client, test_db_session):
    request = LLMRequest(
        caller_type="instagram",
        caller_id="7771",
        prompt="prompt",
        status="failed",
        error_message="encoding_mojibake",
        raw_response='{"tag":"\ufffd\u013a\u00ba\uFFFD\u01AE"}',
    )
    test_db_session.add(request)
    test_db_session.commit()

    response = client.get("/api/v1/instagram/llm/posts/7771")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error_message"] == "encoding_mojibake"
    assert data["result"] is None


def test_instagram_llm_requests_endpoint_includes_failed_mojibake(client, test_db_session):
    request = LLMRequest(
        caller_type="instagram",
        caller_id="7772",
        prompt="prompt",
        status="failed",
        error_message="encoding_mojibake",
    )
    test_db_session.add(request)
    test_db_session.commit()

    response = client.get("/api/v1/instagram/llm/requests?status=failed")

    assert response.status_code == 200
    data = response.json()
    returned = {item["id"]: item for item in data["requests"]}
    assert request.id in returned
    assert returned[request.id]["error_message"] == "encoding_mojibake"


def test_instagram_llm_retry_resets_failed_request_to_pending(client, test_db_session):
    request = LLMRequest(
        caller_type="instagram",
        caller_id="7773",
        prompt="prompt",
        status="failed",
        error_message="encoding_mojibake",
        retry_count=1,
    )
    test_db_session.add(request)
    test_db_session.commit()

    response = client.post(f"/api/v1/instagram/llm/requests/{request.id}/retry")

    assert response.status_code == 200
    test_db_session.refresh(request)
    assert request.status == "pending"
    assert request.error_message is None


def test_instagram_llm_retry_rejects_completed_request(client, test_db_session):
    request = LLMRequest(
        caller_type="instagram",
        caller_id="7774",
        prompt="prompt",
        status="completed",
        result=json.dumps({"tag": "이벤트"}, ensure_ascii=False),
    )
    test_db_session.add(request)
    test_db_session.commit()

    response = client.post(f"/api/v1/instagram/llm/requests/{request.id}/retry")

    assert response.status_code == 400
