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
